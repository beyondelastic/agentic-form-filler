"""Form filler agent that fills PDF forms with extracted data."""
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime

from src.models import AgentState, AgentType, FormFillingResult
from src.llm_client import get_llm_client
from src.tools.pdf_form_filler import PDFFormFillerTool

class FormFillerAgent:
    """
    Form Filler agent that:
    1. Analyzes form templates
    2. Maps extracted data to form fields
    3. Fills forms with appropriate data
    4. Generates output documents
    """
    
    def __init__(self):
        self.agent_type = AgentType.FORM_FILLER
        self.llm_client = get_llm_client()
        self.pdf_filler = PDFFormFillerTool()
    
    async def process(self, state: AgentState) -> AgentState:
        """Process form filling with extracted data and form field information."""
        print(f"\n📝 Form Filler Agent Processing")
        
        try:
            # Validate inputs
            if not state.extracted_data:
                return self._handle_form_error(state, "No extracted data available for form filling")
            
            if not state.form_fields:
                return self._handle_form_error(state, "No form field information available for mapping")
            
            print(f"📊 Available data fields: {len(state.extracted_data)} items")
            print(f"📋 Form fields to fill: {len(state.form_fields)} items")
            
            # Create intelligent mapping between extracted data and form fields
            form_result = await self._create_filled_form(state)
            
            # Update state with results
            state.filled_form_path = form_result.output_file_path
            state.form_filling_status = "completed" if form_result.success else "failed"
            
            # Add results to conversation
            if form_result.success:
                state.messages.append({
                    "role": "assistant",
                    "content": f"✅ Form filling completed successfully!\n"
                              f"   📋 Mapped {len(form_result.filled_fields)} out of {len(state.form_fields)} form fields\n"
                              f"   💾 Output saved to: {form_result.output_file_path}",
                    "agent": self.agent_type.value,
                    "form_result": form_result.dict()
                })
            else:
                state.messages.append({
                    "role": "assistant", 
                    "content": f"❌ Form filling encountered errors: {form_result.errors}",
                    "agent": self.agent_type.value,
                    "form_result": form_result.dict()
                })
            
            # Move to final review
            state.current_step = "final_review"
            state.current_agent = AgentType.ORCHESTRATOR
            
            return state
            
        except Exception as e:
            return self._handle_form_error(state, f"Form filling error: {str(e)}")
    
    async def _create_filled_form(self, state: AgentState) -> FormFillingResult:
        """Create a filled form using the extracted data and PDF form filler tool."""
        
        try:
            # Step 1: Use LLM to intelligently map and format the data for form filling
            print("🧠 Generating intelligent field mapping...")
            mapping_result = await self._generate_form_mapping(state)
            
            # Create output directory if it doesn't exist
            output_dir = "output"
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.splitext(os.path.basename(state.form_template_path or "form"))[0]
            output_filename = f"filled_{base_name}_{timestamp}.pdf"
            output_path = os.path.join(output_dir, output_filename)
            
            # Step 2: Fill the actual PDF form
            print("📝 Filling PDF form with mapped data...")
            
            if not state.form_template_path or not os.path.exists(state.form_template_path):
                raise ValueError(f"Form template not found: {state.form_template_path}")
            
            # Extract mapped fields for PDF filling
            mapped_fields_for_pdf = mapping_result.get("mapped_fields", {})
            # Validate based on mapping quality and form field coverage
            mapping_confidence = mapping_result.get("mapping_confidence", 0)
            expected_form_fields = state.form_fields or state.required_fields or []
            
            if mapping_confidence < 0.3 or len(mapped_fields_for_pdf) == 0:
                print(f"⚠️ Low mapping confidence ({mapping_confidence:.1%}) - using PDF tool semantic matching")
                mapped_fields_for_pdf = state.extracted_data
            
            # Ensure we have data to work with
            if not mapped_fields_for_pdf:
                print(f"❌ No mapped fields available! Using extracted data as fallback.")
                mapped_fields_for_pdf = state.extracted_data or {}
            
            # Use the PDF form filler tool with user context
            form_context = {
                "form_type": "Medical" if "patient" in str(state.form_template_path).lower() else "Generic",
                "domain": self._infer_domain_from_data(state.extracted_data),
                "required_fields": state.required_fields or []
            }
            
            fill_result = self.pdf_filler.fill_pdf_form(
                template_path=state.form_template_path,
                data_mapping=mapped_fields_for_pdf,
                output_path=output_path,
                field_types=state.field_types,
                user_instructions=state.user_instructions,
                form_context=form_context
            )
            
            # Debug: Check the actual filled PDF to verify results
            print(f"🔍 Verifying filled PDF: {output_path}")
            if os.path.exists(output_path):
                import fitz
                verify_doc = fitz.open(output_path)
                verify_page = verify_doc[0]
                verify_widgets = list(verify_page.widgets())
                actual_filled = {}
                for widget in verify_widgets:
                    if widget.field_name and widget.field_value:
                        actual_filled[widget.field_name] = widget.field_value
                verify_doc.close()
                
                print(f"🔍 Actual fields filled in PDF: {len(actual_filled)}")
                print(f"🔍 Actual filled fields: {actual_filled}")
                
                # If there's a discrepancy, report it
                reported_filled = fill_result.get('fields_filled', 0)
                if len(actual_filled) != reported_filled:
                    print(f"⚠️ DISCREPANCY: PDF tool reported {reported_filled} fields, but PDF actually has {len(actual_filled)} fields filled")
                    # Update the result to reflect reality
                    fill_result['fields_filled'] = len(actual_filled)
                    fill_result['filled_fields'] = actual_filled
            
            # Step 3: Create a text summary as backup/reference
            summary_filename = f"filled_{base_name}_{timestamp}_summary.txt"
            summary_path = os.path.join(output_dir, summary_filename)
            
            form_content = self._generate_form_content(mapping_result, state, fill_result)
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(form_content)
            
            # Determine success status
            success = fill_result.get("success", False)
            errors = fill_result.get("errors", [])
            
            if not success and not errors:
                errors = ["PDF form filling completed with warnings"]
            
            print(f"✅ PDF Form saved to: {output_path}")
            print(f"📄 Summary saved to: {summary_path}")
            print(f"📊 Fields filled: {fill_result.get('fields_filled', 0)}/{fill_result.get('total_fields_found', 0)}")
            
            return FormFillingResult(
                output_file_path=output_path,
                filled_fields=fill_result.get("filled_fields", {}),
                success=success,
                errors=errors if errors else None
            )
            
        except Exception as e:
            print(f"❌ Error creating filled form: {str(e)}")
            
            # Fallback: Create text-based form if PDF filling fails
            try:
                print("🔄 Creating text-based fallback form...")
                
                mapping_result = await self._generate_form_mapping(state)
                
                output_dir = "output"
                os.makedirs(output_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                fallback_filename = f"filled_form_text_{timestamp}.txt"
                fallback_path = os.path.join(output_dir, fallback_filename)
                
                form_content = self._generate_form_content(mapping_result, state, {"method": "text_fallback"})
                
                with open(fallback_path, 'w', encoding='utf-8') as f:
                    f.write(form_content)
                
                return FormFillingResult(
                    output_file_path=fallback_path,
                    filled_fields=mapping_result.get("mapped_fields", {}),
                    success=True,
                    errors=[f"PDF filling failed, created text version: {str(e)}"]
                )
                
            except Exception as fallback_error:
                return FormFillingResult(
                    output_file_path="",
                    filled_fields={},
                    success=False,
                    errors=[f"Form filling failed: {str(e)}", f"Fallback failed: {str(fallback_error)}"]
                )
    
    async def _generate_form_mapping(self, state: AgentState) -> Dict[str, Any]:
        """Use LLM to intelligently map extracted data to form fields."""
        
        system_prompt = """You are an intelligent form-filling specialist. Your task is to map extracted data to specific form fields identified from a form template.

CRITICAL REQUIREMENT: You MUST use the EXACT form field names from the template analysis as keys in your mapped_fields response. Do not translate or modify the field names.

INTELLIGENT MAPPING PROCESS:
1. Review the extracted data from the source document (keys and values)
2. Review the EXACT form field names from the template analysis
3. For each form field name, find the most semantically similar extracted data field
4. Map the extracted data VALUE to the EXACT form field NAME
5. Handle different languages, synonyms, and conceptual matches intelligently
6. Format values appropriately for each field type

FIELD NAME MATCHING INTELLIGENCE:
- Match conceptually similar fields across languages (e.g., "diagnosis" → "diagnose", "hospital" → "krankenhaus")
- Handle different naming conventions (camelCase, snake_case, spaces, hyphens)
- Match partial names and abbreviations intelligently
- Consider medical/domain-specific terminology
- Look for semantic relationships, not just string similarity

RESPONSE FORMAT:
```json
{
    "mapped_fields": {
        "exact_form_field_name_from_template": "mapped_value_from_extracted_data",
        "another_exact_field_name": "another_mapped_value"
    },
    "field_mappings_explanation": {
        "exact_form_field_name_from_template": "Explanation of why extracted_data_key was mapped to this field"
    },
    "mapping_confidence": 0.85,
    "missing_fields": ["form_fields_that_could_not_be_filled"],
    "unmapped_data": ["extracted_data_that_was_not_used"],
    "suggestions": "Suggestions for improving the mapping"
}
```

VALUE FORMATTING:
- text: Clean formatting, remove extra whitespace
- number: Convert to numeric format, remove currency symbols  
- date: Standardize to appropriate format (YYYY-MM-DD preferred)
- email: Validate and clean email format
- phone: Standardize phone number format
- checkbox: Use "Yes"/"No" or "true"/"false"
- dropdown: Use exact option values if known

REMEMBER: Use EXACT form field names as keys, but intelligently match their semantic meaning to extracted data."""

        user_message = f"""
EXTRACTED DATA FROM SOURCE DOCUMENT:
{json.dumps(state.extracted_data, indent=2)}

IDENTIFIED FORM FIELDS TO FILL:
{json.dumps(state.form_fields, indent=2)}

FORM FIELD TYPES:
{json.dumps(state.field_types or {}, indent=2)}

REQUIRED FORM FIELDS:
{json.dumps(state.required_fields or [], indent=2)}

USER REQUIREMENTS:
{state.user_instructions or "Standard form filling - map extracted data to form fields as accurately as possible"}

Please provide the optimal mapping of extracted data to the specific form fields identified in the template."""

        try:
            messages = self.llm_client.create_messages(system_prompt, user_message)
            response = await self.llm_client.invoke(messages)
            
            # Parse JSON from response
            response_text = response.content
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                mapping_data = json.loads(json_str)
                mapped_fields = mapping_data.get("mapped_fields", {})
                
                # Validation: Ensure mapped_fields is not empty when we have extracted data
                if not mapped_fields and state.extracted_data:
                    mapping_data["mapped_fields"] = state.extracted_data
                
                # FIXED VALIDATION: Compare mapped fields to expected form fields, not extracted data count
                else:
                    expected_form_fields = len(state.form_fields) if state.form_fields else 0
                    min_expected_mappings = max(1, expected_form_fields * 0.5)  # At least 50% of form fields or minimum 1
                    
                    if len(mapped_fields) < min_expected_mappings:
                        print(f"⚠️ Agent mapping confidence low - using PDF tool semantic matching")
                        mapping_data["mapped_fields"] = state.extracted_data
                        mapping_data["suggestions"] = f"Agent mapping produced {len(mapped_fields)}/{expected_form_fields} field mappings (below 50% threshold). Using PDF tool semantic matching."
                
                return mapping_data
            else:
                # Fallback mapping
                print(f"⚠️ JSON parsing failed - using fallback mapping")
                return {
                    "mapped_fields": state.extracted_data,
                    "mapping_confidence": 0.5,
                    "missing_fields": [],
                    "suggestions": "Used direct data due to parsing issues - PDF tool will handle semantic matching"
                }
                
        except Exception as e:
            print(f"❌ Mapping generation error: {str(e)}")
            
            # Ensure we have a valid dict for fallback
            fallback_data = state.extracted_data if isinstance(state.extracted_data, dict) else {}
            
            return {
                "mapped_fields": fallback_data,
                "mapping_confidence": 0.3,
                "missing_fields": [],
                "suggestions": f"Error in mapping: {str(e)}. Using fallback data with {len(fallback_data)} fields."
            }
    
    def _generate_form_content(self, mapping_result: Dict[str, Any], state: AgentState, fill_result: Optional[Dict[str, Any]] = None) -> str:
        """Generate the actual form content summary."""
        
        content = []
        content.append("=" * 60)
        content.append("FILLED FORM DOCUMENT")
        content.append("=" * 60)
        content.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        # Handle multiple source documents
        if state.pdf_file_paths and len(state.pdf_file_paths) > 1:
            content.append(f"Source Documents:")
            for i, doc_path in enumerate(state.pdf_file_paths, 1):
                content.append(f"  {i}. {doc_path}")
        else:
            content.append(f"Source Document: {state.pdf_file_path or state.pdf_file_paths[0] if state.pdf_file_paths else 'N/A'}")
        content.append(f"Template: {state.form_template_path or 'Generic Template'}")
        
        # Add PDF filling results if available
        if fill_result:
            content.append("")
            content.append("PDF FILLING RESULTS:")
            content.append("-" * 40)
            content.append(f"Method: {fill_result.get('method', 'unknown')}")
            content.append(f"Success: {fill_result.get('success', False)}")
            content.append(f"Fields Found: {fill_result.get('total_fields_found', 0)}")
            content.append(f"Fields Filled: {fill_result.get('fields_filled', 0)}")
            
            if fill_result.get('errors'):
                content.append(f"Errors: {', '.join(fill_result['errors'])}")
        
        content.append("")
        
        # Add actual PDF form fields that were filled
        content.append("PDF FORM FIELDS FILLED:")
        content.append("-" * 40)
        
        # Show only the fields that were actually filled in the PDF
        filled_fields = fill_result.get('filled_fields', {}) if fill_result else {}
        if filled_fields:
            for field_name, field_value in filled_fields.items():
                # Format field name nicely
                display_name = field_name.replace('_', ' ').title()
                content.append(f"{display_name:.<30} {str(field_value)[:60]}{'...' if len(str(field_value)) > 60 else ''}")
        else:
            content.append("No fields were filled in the PDF form.")
        
        # Add extracted data summary section
        content.append("")
        content.append("EXTRACTED DATA SUMMARY:")
        content.append("-" * 40)
        extracted_data = state.extracted_data or {}
        if extracted_data:
            content.append(f"Total data fields extracted: {len(extracted_data)}")
            content.append(f"Key data categories found:")
            
            # Group data by categories for summary
            categories = self._categorize_extracted_data(extracted_data)
            for category, count in categories.items():
                content.append(f"  • {category}: {count} fields")
        else:
            content.append("No data was extracted.")
        
        content.append("")
        
        # Add mapping information
        confidence = mapping_result.get("mapping_confidence", 0.0)
        content.append(f"Mapping Confidence: {confidence:.0%}")
        
        # Fix suggestion message to be accurate
        suggestions = mapping_result.get("suggestions", "")
        if "low confidence" in suggestions and confidence > 0.8:
            # Correct the misleading message
            suggestions = f"Used direct data approach with PDF tool semantic matching - achieved {confidence:.0%} success rate"
        
        missing_fields = mapping_result.get("missing_fields", [])
        if missing_fields:
            content.append(f"Missing Fields: {', '.join(missing_fields)}")
        
        suggestions = mapping_result.get("suggestions", "")
        if suggestions:
            content.append("")
            content.append("SUGGESTIONS:")
            content.append("-" * 40)
            content.append(suggestions)
        
        content.append("")
        content.append("=" * 60)
        content.append("END OF FORM")
        content.append("=" * 60)
        
        return "\n".join(content)
    
    def _infer_domain_from_data(self, extracted_data: Dict[str, Any]) -> str:
        """Infer the domain/type from extracted data."""
        if not extracted_data:
            return "General"
            
        # Convert to string for analysis
        data_str = str(extracted_data).lower()
        
        # Medical indicators
        medical_terms = ["patient", "diagnosis", "medication", "treatment", "medical", "clinical", "pathology", "lab"]
        if any(term in data_str for term in medical_terms):
            return "Medical"
            
        # Legal indicators  
        legal_terms = ["court", "case", "legal", "contract", "agreement", "plaintiff", "defendant"]
        if any(term in data_str for term in legal_terms):
            return "Legal"
            
        # Insurance indicators
        insurance_terms = ["policy", "claim", "coverage", "premium", "deductible", "beneficiary"]
        if any(term in data_str for term in insurance_terms):
            return "Insurance"
            
        # HR indicators
        hr_terms = ["employee", "department", "salary", "benefits", "performance", "hiring"]
        if any(term in data_str for term in hr_terms):
            return "HR"
            
        return "General"
    
    def _categorize_extracted_data(self, extracted_data: Dict[str, Any]) -> Dict[str, int]:
        """Categorize extracted data fields for summary reporting."""
        categories = {
            "Patient Information": 0,
            "Medical Data": 0,
            "Lab Results": 0,
            "Dates": 0,
            "Administrative": 0,
            "Other": 0
        }
        
        for field_name in extracted_data.keys():
            field_lower = field_name.lower()
            
            # Patient information
            if any(term in field_lower for term in ["patient", "name", "id", "nummer"]):
                categories["Patient Information"] += 1
            # Medical data
            elif any(term in field_lower for term in ["diagnosis", "treatment", "medication", "pathology", "tumor", "cancer", "stage", "tnm"]):
                categories["Medical Data"] += 1
            # Lab results
            elif any(term in field_lower for term in ["lab", "test", "result", "value", "parameter", "hb", "leuko", "creatinine"]):
                categories["Lab Results"] += 1
            # Dates
            elif any(term in field_lower for term in ["date", "datum", "time"]):
                categories["Dates"] += 1
            # Administrative
            elif any(term in field_lower for term in ["hospital", "clinic", "department", "case", "fall", "report"]):
                categories["Administrative"] += 1
            else:
                categories["Other"] += 1
        
        # Remove empty categories
        return {k: v for k, v in categories.items() if v > 0}
    
    def _handle_form_error(self, state: AgentState, error_message: str) -> AgentState:
        """Handle form filling errors and update state."""
        print(f"❌ {error_message}")
        
        state.messages.append({
            "role": "assistant",
            "content": f"❌ Form filling failed: {error_message}",
            "agent": self.agent_type.value,
            "error": error_message
        })
        
        # Return to orchestrator for error handling  
        state.current_step = "final_review"
        state.current_agent = AgentType.ORCHESTRATOR
        state.filled_form_path = None
        state.form_filling_status = "failed"
        
        return state
