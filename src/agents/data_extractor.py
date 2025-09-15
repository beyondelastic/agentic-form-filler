"""Data extractor agent that extracts information from PDF documents."""
import os
import json
from typing import Dict, Any, Optional
import PyPDF2
import pdfplumber

from src.models import AgentState, AgentType, ExtractionResult, FormAnalysisResult
from src.llm_client import get_llm_client
from src.tools.azure_doc_intelligence import AzureDocumentIntelligenceTool
from src.config import config

class DataExtractorAgent:
    """
    Data Extractor agent that:
    1. Reads PDF documents and extracts data
    2. Analyzes PDF form templates to identify fields
    3. Uses LLM to structure and enhance extracted data
    4. Returns both extracted data and form field information
    """
    
    def __init__(self):
        self.agent_type = AgentType.DATA_EXTRACTOR
        self.llm_client = get_llm_client()
        self.azure_doc_intelligence = AzureDocumentIntelligenceTool()
        self.use_azure_doc_intelligence = self.azure_doc_intelligence.is_available()
    
    async def process(self, state: AgentState) -> AgentState:
        """Process data extraction from PDF document and form analysis."""
        print(f"\n📄 Data Extractor Agent Processing")
        
        try:
            # Step 1: Extract data from input documents
            print("🔍 Step 1: Extracting data from input documents...")
            
            # Get list of files to process
            files_to_process = state.pdf_file_paths if state.pdf_file_paths else [state.pdf_file_path] if state.pdf_file_path else []
            
            if not files_to_process:
                return self._handle_extraction_error(state, "No PDF files specified for extraction")
            
            print(f"📄 Processing {len(files_to_process)} document(s): {[os.path.basename(f) for f in files_to_process]}")
            
            # Process each file and combine results
            all_extracted_data = {}
            total_confidence = 0.0
            processed_files = []
            
            for file_path in files_to_process:
                print(f"📊 Analyzing document: {os.path.basename(file_path)}")
                
                # Temporarily set current file for existing methods
                original_path = state.pdf_file_path
                state.pdf_file_path = file_path
                
                if self.use_azure_doc_intelligence:
                    single_result = await self._extract_with_azure_doc_intelligence(state)
                else:
                    # Fallback to basic text extraction + LLM
                    single_result = await self._extract_with_text_and_llm(state)
                
                # Restore original path
                state.pdf_file_path = original_path
                
                if single_result:
                    # Merge extracted data with prefixes to avoid conflicts
                    file_prefix = os.path.splitext(os.path.basename(file_path))[0]
                    for key, value in single_result.extracted_fields.items():
                        # Use original key if unique, otherwise prefix with filename
                        final_key = key
                        if key in all_extracted_data:
                            final_key = f"{file_prefix}_{key}"
                        all_extracted_data[final_key] = value
                    
                    total_confidence += single_result.confidence_score
                    processed_files.append(file_path)
                    print(f"✅ Extracted {len(single_result.extracted_fields)} fields from {os.path.basename(file_path)}")
                else:
                    print(f"❌ Failed to extract data from {os.path.basename(file_path)}")
            
            if not all_extracted_data:
                return self._handle_extraction_error(state, "Could not extract data from any documents")
            
            # Create combined extraction result
            average_confidence = total_confidence / len(processed_files) if processed_files else 0.0
            
            extraction_result = ExtractionResult(
                extracted_fields=all_extracted_data,
                confidence_score=average_confidence,
                source_file=f"{len(processed_files)} documents",
                extraction_method="Azure Document Intelligence (Multi-file)" if self.use_azure_doc_intelligence else "Text + LLM (Multi-file)"
            )
            
            # Step 2: Analyze form template to identify fields
            print("📋 Step 2: Analyzing form template...")
            form_analysis_result = await self._analyze_form_template(state)
            
            if not form_analysis_result:
                return self._handle_extraction_error(state, "Could not analyze form template")
            
            # Update state with results
            state.extracted_data = extraction_result.extracted_fields
            state.extraction_confidence = extraction_result.confidence_score
            state.form_fields = form_analysis_result.form_fields
            state.field_types = form_analysis_result.field_types
            state.required_fields = form_analysis_result.required_fields
            state.form_analysis_confidence = form_analysis_result.confidence_score
            
            # Add results to conversation
            method_name = extraction_result.extraction_method
            file_list = [os.path.basename(f) for f in processed_files]
            state.messages.append({
                "role": "assistant",
                "content": f"✅ Data extraction completed using {method_name}.\n"
                          f"   📄 Processed files: {', '.join(file_list)}\n"
                          f"   📊 Found {len(extraction_result.extracted_fields)} data fields with {extraction_result.confidence_score:.0%} confidence\n"
                          f"   📋 Identified {len(form_analysis_result.form_fields)} form fields with {form_analysis_result.confidence_score:.0%} confidence\n"
                          f"   🎯 Required form fields: {', '.join(form_analysis_result.required_fields)}",
                "agent": self.agent_type.value,
                "extraction_result": extraction_result.dict(),
                "form_analysis_result": form_analysis_result.dict()
            })
            
            # Move to next step
            state.current_step = "reviewing_extraction"
            state.current_agent = AgentType.ORCHESTRATOR
            
            return state
            
        except Exception as e:
            return self._handle_extraction_error(state, f"Extraction error: {str(e)}")
    
    async def _extract_with_azure_doc_intelligence(self, state: AgentState) -> Optional[ExtractionResult]:
        """Extract data using Azure Document Intelligence."""
        if not state.pdf_file_path or not os.path.exists(state.pdf_file_path):
            print(f"❌ PDF file not found: {state.pdf_file_path}")
            return None
        
        try:
            print("🔍 Using Azure Document Intelligence for data extraction...")
            
            # Extract using Azure Document Intelligence
            azure_result = self.azure_doc_intelligence.extract_from_file(
                state.pdf_file_path,
                include_tables=True,
                include_cell_content=False
            )
            
            # Convert to our ExtractionResult format
            extracted_fields = azure_result.get("key_values", {})
            confidence_scores = azure_result.get("kv_confidence", {})
            
            # Calculate overall confidence
            overall_confidence = azure_result.get("average_confidence", 0.0)
            
            # Enhance with LLM if user provided specific instructions
            if state.user_instructions and extracted_fields:
                enhanced_fields = await self._enhance_extraction_with_llm(
                    extracted_fields, state.user_instructions
                )
                extracted_fields.update(enhanced_fields)
            
            return ExtractionResult(
                extracted_fields=extracted_fields,
                confidence_score=overall_confidence,
                source_file=state.pdf_file_path,
                extraction_method="azure_document_intelligence",
                errors=None
            )
            
        except Exception as e:
            print(f"❌ Azure Document Intelligence extraction failed: {str(e)}")
            print("🔄 Falling back to text-based extraction...")
            
            # Fallback to text extraction
            return await self._extract_with_text_and_llm(state)
    
    async def _extract_with_text_and_llm(self, state: AgentState) -> Optional[ExtractionResult]:
        """Extract data using text extraction + LLM (fallback method)."""
        try:
            # Extract text from PDF
            pdf_text = await self._extract_pdf_text(state.pdf_file_path)
            
            if not pdf_text:
                return None
            
            # Use LLM to structure the data
            return await self._extract_structured_data(pdf_text, state.user_instructions)
            
        except Exception as e:
            print(f"❌ Text + LLM extraction failed: {str(e)}")
            return None
    
    async def _enhance_extraction_with_llm(
        self, 
        extracted_data: Dict[str, Any], 
        user_instructions: str
    ) -> Dict[str, Any]:
        """Use LLM to enhance and refine extracted data based on user instructions."""
        
        system_prompt = """You are a data enhancement specialist. Your task is to review extracted data and enhance it based on user requirements.

INSTRUCTIONS:
1. Review the extracted key-value pairs
2. Consider the user's specific requirements
3. Add any missing fields that should be extracted
4. Standardize formats and naming conventions
5. Fill in derived or calculated fields if needed

Return ONLY the additional/enhanced fields as JSON. Do not duplicate existing fields unless you're improving them.

RESPONSE FORMAT:
```json
{
    "enhanced_field": "value",
    "derived_field": "calculated_value"
}
```"""

        user_message = f"""
EXTRACTED DATA:
{json.dumps(extracted_data, indent=2)}

USER REQUIREMENTS:
{user_instructions}

Please provide any additional fields or enhancements based on the requirements."""

        try:
            messages = self.llm_client.create_messages(system_prompt, user_message)
            response = await self.llm_client.invoke(messages)
            
            # Parse JSON from response
            response_text = response.content
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                enhanced_data = json.loads(json_str)
                return enhanced_data
            
            return {}
            
        except Exception as e:
            print(f"⚠️ LLM enhancement failed: {str(e)}")
            return {}
    
    async def _extract_pdf_text(self, pdf_path: Optional[str]) -> Optional[str]:
        """Extract text content from PDF file."""
        if not pdf_path or not os.path.exists(pdf_path):
            print(f"❌ PDF file not found: {pdf_path}")
            return None
        
        try:
            print(f"📖 Reading PDF: {pdf_path}")
            
            # Try pdfplumber first (better for complex layouts)
            with pdfplumber.open(pdf_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                
                if text_parts:
                    full_text = "\n\n".join(text_parts)
                    print(f"✅ Extracted {len(full_text)} characters from {len(text_parts)} pages")
                    return full_text
            
            # Fallback to PyPDF2
            print("🔄 Trying fallback extraction method...")
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text_parts = []
                
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text())
                
                if text_parts:
                    full_text = "\n\n".join(text_parts)
                    print(f"✅ Extracted {len(full_text)} characters using fallback method")
                    return full_text
            
            return None
            
        except Exception as e:
            print(f"❌ Error extracting PDF text: {str(e)}")
            return None
    
    async def _extract_structured_data(self, pdf_text: str, user_instructions: Optional[str]) -> ExtractionResult:
        """Use LLM to extract structured data from PDF text."""
        
        system_prompt = """You are a data extraction specialist. Your task is to extract relevant information from document text and structure it as JSON.

INSTRUCTIONS:
1. Read the document text carefully
2. Identify key information based on user requirements
3. Extract data into a structured JSON format
4. Assign confidence scores (0.0 to 1.0) based on clarity and certainty
5. Use consistent field names and formats

For medical documents, typical fields might include: patient_name, date_of_birth, diagnosis, test_results, doctor_name, date
For invoices: company_name, invoice_number, date, amount, items
For contracts: parties, agreement_date, terms, signatures

RESPONSE FORMAT:
```json
{
    "extracted_fields": {
        "field_name": "extracted_value",
        "another_field": "another_value"
    },
    "confidence_score": 0.85,
    "extraction_notes": "Brief notes about extraction quality"
}
```

Be thorough but only extract information that is clearly present in the document."""

        user_message = f"""
DOCUMENT TEXT:
{pdf_text[:4000]}  # Limit to prevent token overflow

USER REQUIREMENTS:
{user_instructions or "Extract all relevant structured data from this document"}

Please extract the structured data as JSON."""

        try:
            messages = self.llm_client.create_messages(system_prompt, user_message)
            response = await self.llm_client.invoke(messages)
            
            # Parse JSON from response
            response_text = response.content
            
            # Extract JSON from response (handle markdown code blocks)
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                extracted_data = json.loads(json_str)
                
                return ExtractionResult(
                    extracted_fields=extracted_data.get("extracted_fields", {}),
                    confidence_score=extracted_data.get("confidence_score", 0.7),
                    source_file=pdf_text[:100] + "...",  # First 100 chars for reference
                    extraction_method="llm_structured",
                    errors=None
                )
            else:
                # Fallback: treat entire response as extracted data
                return ExtractionResult(
                    extracted_fields={"raw_extraction": response_text},
                    confidence_score=0.5,
                    source_file=pdf_text[:100] + "...",
                    extraction_method="llm_fallback",
                    errors=["Could not parse JSON from LLM response"]
                )
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {str(e)}")
            return ExtractionResult(
                extracted_fields={"extraction_error": response_text if 'response' in locals() else "No response"},
                confidence_score=0.3,
                source_file=pdf_text[:100] + "...",
                extraction_method="error_fallback",
                errors=[f"JSON parsing failed: {str(e)}"]
            )
        except Exception as e:
            print(f"❌ LLM extraction error: {str(e)}")
            return ExtractionResult(
                extracted_fields={"error": str(e)},
                confidence_score=0.0,
                source_file=pdf_text[:100] + "...",
                extraction_method="error",
                errors=[str(e)]
            )
    
    async def _analyze_form_template(self, state: AgentState) -> Optional[FormAnalysisResult]:
        """Analyze form template to identify fields that need to be filled."""
        if not state.form_template_path or not os.path.exists(state.form_template_path):
            print(f"❌ Form template file not found: {state.form_template_path}")
            return None
        
        try:
            # Primary approach: Use LLM analysis which is better for form field detection
            # Azure Document Intelligence "prebuilt-document" is optimized for filled forms, not templates
            print("🔍 Analyzing form template with LLM (optimized for empty form fields)...")
            llm_analysis = await self._analyze_form_fields_with_llm(state.form_template_path)
            
            # Secondary: Try Azure Document Intelligence for additional context if available
            if self.use_azure_doc_intelligence and llm_analysis:
                try:
                    print("📊 Supplementing with Azure Document Intelligence layout analysis...")
                    azure_result = self.azure_doc_intelligence.extract_from_file(
                        state.form_template_path,
                        include_tables=True,
                        include_cell_content=False
                    )
                    
                    # Use Azure for layout/structure info, but rely on LLM for field identification
                    azure_fields = azure_result.get("key_values", {})
                    azure_confidence = azure_result.get("average_confidence", 0.0)
                    
                    # Merge Azure findings with LLM analysis (LLM takes precedence)
                    combined_fields = llm_analysis.form_fields.copy()
                    
                    # Add any additional fields found by Azure that weren't caught by LLM
                    for azure_key, azure_value in azure_fields.items():
                        if azure_key not in combined_fields:
                            combined_fields[azure_key] = azure_value
                            # Add to field types if not already present
                            if azure_key not in llm_analysis.field_types:
                                llm_analysis.field_types[azure_key] = "text"
                    
                    # Boost confidence if both methods agree
                    final_confidence = min(0.95, llm_analysis.confidence_score + (azure_confidence * 0.1))
                    
                    return FormAnalysisResult(
                        form_fields=combined_fields,
                        field_types=llm_analysis.field_types,
                        required_fields=llm_analysis.required_fields,
                        confidence_score=final_confidence,
                        source_file=state.form_template_path,
                        analysis_method="llm_primary_azure_supplemented",
                        errors=None
                    )
                    
                except Exception as azure_error:
                    print(f"⚠️ Azure Document Intelligence supplemental analysis failed: {azure_error}")
                    # Return LLM analysis as fallback
                    return llm_analysis
            else:
                # Return pure LLM analysis
                return llm_analysis
                
        except Exception as e:
            print(f"❌ Form analysis failed: {str(e)}")
            return None
    
    async def _analyze_form_fields_with_llm(self, form_path: str) -> Optional[FormAnalysisResult]:
        """Analyze form fields using text extraction and LLM."""
        try:
            # Extract text from form template
            form_text = await self._extract_pdf_text(form_path)
            if not form_text:
                return None
            
            system_prompt = """You are an expert form analysis specialist. Your task is to analyze a PDF form template and identify ALL fields that need to be filled.

FIELD DETECTION STRATEGY:
1. Look for field labels followed by colons (:)
2. Identify underscores, dashes, or blank lines indicating input areas
3. Find checkbox squares (☐) or circles (○) 
4. Detect dropdown indicators or selection areas
5. Look for signature lines or date fields
6. Identify any bracketed placeholders like [Name], [Date], etc.
7. Find fields marked with asterisks (*) or "Required"

FIELD TYPE IDENTIFICATION:
- **text**: Name, address, comments, general text fields
- **number**: Amount, quantity, ID numbers, codes
- **date**: Birth date, appointment date, expiry date
- **email**: Email address fields
- **phone**: Phone number, mobile, fax
- **checkbox**: Yes/No options, checkboxes, selections
- **dropdown**: List of options, selection menus
- **signature**: Signature areas, authorization fields

Return your analysis as JSON with this exact structure:
```json
{
    "form_fields": {
        "patient_name": "Patient Name:",
        "date_of_birth": "Date of Birth:",
        "phone_number": "Phone:",
        "emergency_contact": "Emergency Contact:"
    },
    "field_types": {
        "patient_name": "text",
        "date_of_birth": "date", 
        "phone_number": "phone",
        "emergency_contact": "text"
    },
    "required_fields": ["patient_name", "date_of_birth"],
    "field_descriptions": {
        "patient_name": "Full name of the patient",
        "date_of_birth": "Patient's birth date in MM/DD/YYYY format"
    }
}
```

Be thorough and identify EVERY possible input field, even if it seems minor. Empty form templates often have subtle indicators for fields."""

            user_prompt = f"""Please analyze this PDF form template and identify all fields:

FORM CONTENT:
{form_text[:4000]}  # Limit text to avoid token limits

Identify all form fields, their types, and requirements."""

            messages = self.llm_client.create_messages(system_prompt, user_prompt)
            response = await self.llm_client.invoke(messages)
            response_text = response.content

            # Parse JSON response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                form_analysis = json.loads(json_str)
                
                return FormAnalysisResult(
                    form_fields=form_analysis.get("form_fields", {}),
                    field_types=form_analysis.get("field_types", {}),
                    required_fields=form_analysis.get("required_fields", []),
                    confidence_score=0.8,  # LLM analysis confidence
                    source_file=form_path,
                    analysis_method="text_extraction_llm",
                    errors=None
                )
            else:
                # Fallback if JSON parsing fails
                return FormAnalysisResult(
                    form_fields={"analysis_text": response_text},
                    field_types={"analysis_text": "text"},
                    required_fields=[],
                    confidence_score=0.3,
                    source_file=form_path,
                    analysis_method="llm_fallback",
                    errors=["Could not parse structured form analysis"]
                )

        except Exception as e:
            print(f"❌ LLM form analysis failed: {str(e)}")
            return None

    def _handle_extraction_error(self, state: AgentState, error_message: str) -> AgentState:
        """Handle extraction errors and update state."""
        print(f"❌ {error_message}")
        
        state.messages.append({
            "role": "assistant",
            "content": f"❌ Data extraction failed: {error_message}",
            "agent": self.agent_type.value,
            "error": error_message
        })
        
        # Return to orchestrator for error handling
        state.current_step = "reviewing_extraction"  
        state.current_agent = AgentType.ORCHESTRATOR
        state.extracted_data = None
        state.extraction_confidence = 0.0
        
        return state
