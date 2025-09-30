"""Form filler agent that fills forms using semantic extraction and form learning insights."""
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime

from src.models import AgentState, AgentType, FormFillingResult
from src.tools.semantic_form_filler import SemanticFormFillerTool

class FormFillerAgent:
    """
    Enhanced Form Filler agent that:
    1. Uses semantic extraction results and form learning insights
    2. Creates intelligent field mappings without redundant LLM processing
    3. Fills forms with high accuracy using comprehensive context
    4. Generates detailed output and mapping reports
    """
    
    def __init__(self):
        self.agent_type = AgentType.FORM_FILLER
        self.semantic_filler = SemanticFormFillerTool()
    
    async def process(self, state: AgentState) -> AgentState:
        """Process form filling using semantic extraction and form learning insights."""
        print(f"\n📝 Enhanced Form Filler Agent Processing")
        
        try:
            # Validate inputs - we now require both extracted_data and form_structure
            if not state.extracted_data:
                return self._handle_form_error(state, "No semantic extraction data available for form filling")
            
            # Check if we have form learning insights (preferred) or fallback to basic fields
            form_structure = getattr(state, 'form_structure', None)
            if not form_structure and not getattr(state, 'form_fields', None):
                return self._handle_form_error(state, "No form structure or field information available")
            
            print(f"📊 Available extracted fields: {len(state.extracted_data)} items")
            if form_structure:
                total_form_fields = sum(len(section.get('fields', [])) for section in form_structure.get('sections', []))
                print(f"🧠 Form structure available: {len(form_structure.get('sections', []))} sections, {total_form_fields} fields")
            else:
                print(f"📋 Basic form fields available: {len(getattr(state, 'form_fields', []))} items")
            
            # Generate output path
            output_path = self._generate_output_path(state)
            
            # Use semantic form filler
            semantic_result = await self.semantic_filler.fill_form_semantically(state, output_path)
            
            # Convert semantic result to FormFillingResult for compatibility
            form_result = self._convert_semantic_result(semantic_result)
            
            # Update state with results
            state.filled_form_path = form_result.output_file_path
            state.form_filling_status = "completed" if form_result.success else "failed"
            
            # Add enhanced results to conversation
            if form_result.success:
                # Calculate mapping statistics from semantic result
                high_conf_mappings = len([m for m in semantic_result.semantic_mappings if m.confidence >= 0.8])
                medium_conf_mappings = len([m for m in semantic_result.semantic_mappings if 0.5 <= m.confidence < 0.8])
                
                state.messages.append({
                    "role": "assistant",
                    "content": f"✅ Semantic form filling completed successfully!\n"
                              f"   🎯 Created {len(semantic_result.semantic_mappings)} semantic mappings\n"
                              f"   📋 Fields filled: {semantic_result.fields_filled}/{semantic_result.total_form_fields}\n"
                              f"   🏆 High confidence: {high_conf_mappings}, Medium: {medium_conf_mappings}\n"
                              f"   💾 Output saved to: {form_result.output_file_path}",
                    "agent": self.agent_type.value,
                    "semantic_mappings": len(semantic_result.semantic_mappings),
                    "high_confidence_fields": high_conf_mappings
                })
            else:
                state.messages.append({
                    "role": "assistant", 
                    "content": f"❌ Semantic form filling encountered errors: {form_result.errors}",
                    "agent": self.agent_type.value,
                    "errors": form_result.errors
                })
            
            # Move to final review with quality checking
            state.current_step = "final_review"
            state.current_agent = None  # Let workflow route to quality checker
            
            return state
            
        except Exception as e:
            return self._handle_form_error(state, f"Semantic form filling error: {str(e)}")
    
    def _generate_output_path(self, state: AgentState) -> str:
        """Generate appropriate output path for the filled form."""
        try:
            from src.config import config
            output_dir = config.OUTPUT_DIR
            os.makedirs(output_dir, exist_ok=True)
            
            # Determine file extension and create output filename
            if state.form_template_path and os.path.exists(state.form_template_path):
                file_extension = os.path.splitext(state.form_template_path)[1].lower()
                base_name = os.path.splitext(os.path.basename(state.form_template_path))[0]
            else:
                file_extension = '.txt'  # Fallback
                base_name = "form"
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"filled_{base_name}_{timestamp}{file_extension}"
            
            return os.path.join(output_dir, output_filename)
            
        except Exception as e:
            # Fallback path
            return f"./filled_form_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    def _convert_semantic_result(self, semantic_result) -> FormFillingResult:
        """Convert SemanticFormFillingResult to FormFillingResult for compatibility."""
        
        # Extract filled fields from semantic mappings
        filled_fields = {}
        for mapping in semantic_result.semantic_mappings:
            filled_fields[mapping.form_field_id] = mapping.extracted_value
        
        return FormFillingResult(
            output_file_path=semantic_result.output_file_path,
            filled_fields=filled_fields,
            success=semantic_result.success,
            errors=semantic_result.errors
        )

    # Legacy method - kept for compatibility, now deprecated
    async def _create_filled_form(self, state: AgentState) -> FormFillingResult:
        """Legacy method - now uses semantic form filler internally."""
        print("⚠️ Using legacy _create_filled_form - consider updating to semantic approach")
        
        # Redirect to semantic approach
        output_path = self._generate_output_path(state)
        semantic_result = await self.semantic_filler.fill_form_semantically(state, output_path)
        return self._convert_semantic_result(semantic_result)
    
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
    
    async def _fill_excel_form(self, state: AgentState, mapping_result: Dict[str, Any], output_path: str) -> FormFillingResult:
        """Fill Excel form using ExcelFormFillerTool."""
        try:
            # Extract mapped fields for Excel filling
            mapped_fields_for_excel = mapping_result.get("mapped_fields", {})
            
            # Validate mapping quality
            mapping_confidence = mapping_result.get("mapping_confidence", 0)
            
            if mapping_confidence < 0.3 or len(mapped_fields_for_excel) == 0:
                print(f"⚠️ Low mapping confidence ({mapping_confidence:.1%}) - using Excel tool semantic matching")
                mapped_fields_for_excel = state.extracted_data
            
            # Ensure we have data to work with
            if not mapped_fields_for_excel:
                print(f"❌ No mapped fields available! Using extracted data as fallback.")
                mapped_fields_for_excel = state.extracted_data or {}
            
            # Use the Excel form filler tool
            fill_result = self.excel_filler.fill_excel_form(
                template_path=str(state.form_template_path),
                data_mapping=mapped_fields_for_excel,
                output_path=output_path
            )
            
            # Create a text summary as backup/reference
            from src.config import config
            output_dir = config.OUTPUT_DIR
            base_name = os.path.splitext(os.path.basename(output_path))[0]
            summary_filename = f"{base_name}_summary.txt"
            summary_path = os.path.join(output_dir, summary_filename)
            
            form_content = self._generate_form_content(mapping_result, state, fill_result)
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(form_content)
            
            # Determine success status
            success = fill_result.get("success", False)
            errors = fill_result.get("errors", [])
            
            if not success and not errors:
                errors = ["Excel form filling completed with warnings"]
            
            print(f"✅ Excel Form saved to: {output_path}")
            print(f"📄 Summary saved to: {summary_path}")
            print(f"📊 Fields filled: {fill_result.get('fields_filled', 0)}")
            
            return FormFillingResult(
                output_file_path=output_path,
                filled_fields=fill_result.get("filled_fields", {}),
                success=success,
                errors=errors if errors else None
            )
            
        except Exception as e:
            print(f"❌ Error filling Excel form: {str(e)}")
            return FormFillingResult(
                output_file_path="",
                filled_fields={},
                success=False,
                errors=[f"Excel form filling failed: {str(e)}"]
            )
    
    async def _fill_pdf_form(self, state: AgentState, mapping_result: Dict[str, Any], output_path: str) -> FormFillingResult:
        """Fill PDF form using integrated semantic form filling."""
        try:
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
            
            # Create a text summary as backup/reference
            from src.config import config
            output_dir = config.OUTPUT_DIR
            base_name = os.path.splitext(os.path.basename(output_path))[0]
            summary_filename = f"{base_name}_summary.txt"
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
            print(f"❌ Error filling PDF form: {str(e)}")
            return FormFillingResult(
                output_file_path="",
                filled_fields={},
                success=False,
                errors=[f"PDF form filling failed: {str(e)}"]
            )

    async def _save_mapping_json(self, mapping_result: Dict[str, Any], state: AgentState) -> None:
        """Save field mapping results to JSON file for logging and debugging."""
        try:
            from datetime import datetime
            import json
            from src.config import config
            
            # Create output directory if it doesn't exist
            os.makedirs(config.OUTPUT_DIR, exist_ok=True)
            
            # Create comprehensive mapping log
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"field_mapping_{timestamp}.json"
            filepath = os.path.join(config.OUTPUT_DIR, filename)
            
            # Prepare JSON data with both input and output
            mapping_data = {
                "timestamp": datetime.now().isoformat(),
                "form_template": os.path.basename(state.form_template_path) if state.form_template_path else "unknown",
                "input_data": {
                    "extracted_fields_count": len(state.extracted_data) if state.extracted_data else 0,
                    "extracted_data": state.extracted_data or {},
                    "form_fields_count": len(state.form_fields) if state.form_fields else 0,
                    "available_form_fields": list(state.form_fields.keys()) if state.form_fields else [],
                    "required_fields": state.required_fields or []
                },
                "mapping_result": mapping_result,
                "metadata": {
                    "processor": "FormFillerAgent", 
                    "version": "1.0"
                }
            }
            
            # Save to JSON file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 Field mapping saved to: {filename}")
            
        except Exception as e:
            print(f"⚠️ Could not save mapping JSON: {str(e)}")
