"""Data extractor agent that extracts information from PDF documents using semantic analysis."""
import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.models import AgentState, AgentType
from src.llm_client import get_llm_client
from src.tools.semantic_data_extractor import SemanticDataExtractor, FieldExtractionRequest
from src.config import config

class DataExtractorAgent:
    """
    Data Extractor agent that:
    1. Uses form learning insights to understand document structure
    2. Performs semantic extraction of field data from documents
    3. Validates and formats extracted data based on field types
    4. Returns structured extraction results with confidence scores
    """
    
    def __init__(self):
        self.agent_type = AgentType.DATA_EXTRACTOR
        self.llm_client = get_llm_client()
        self.semantic_extractor = SemanticDataExtractor()
    
    async def process(self, state: AgentState) -> AgentState:
        """Process semantic data extraction from documents using form learning insights."""
        print(f"\n📄 Data Extractor Agent Processing (Semantic Extraction)")
        
        try:
            # Check if form learning has been completed
            if not hasattr(state, 'form_structure') or not state.form_structure:
                return self._handle_extraction_error(state, "Form learning required before data extraction. Please run form analysis first.")
            
            # Get list of files to process
            files_to_process = state.pdf_file_paths if state.pdf_file_paths else [state.pdf_file_path] if state.pdf_file_path else []
            
            if not files_to_process:
                return self._handle_extraction_error(state, "No PDF files specified for extraction")
            
            print(f"📄 Processing {len(files_to_process)} document(s) for semantic extraction:")
            for file_path in files_to_process:
                print(f"   - {os.path.basename(file_path)}")
            
            # Create extraction requests based on form structure
            extraction_requests = self._create_extraction_requests_from_form_structure(state.form_structure)
            
            if not extraction_requests:
                return self._handle_extraction_error(state, "No extractable fields found in form structure")
            
            print(f"🎯 Identified {len(extraction_requests)} fields for semantic extraction")
            
            # Process semantic extraction for all files
            semantic_results = await self.semantic_extractor.extract_form_data(
                document_paths=files_to_process,
                form_fields=state.form_fields or {},
                form_learning_data=state.form_structure
            )
            
            if not semantic_results:
                return self._handle_extraction_error(state, "Semantic extraction failed - no data found")
            
            # Transform semantic results to extracted data format
            extracted_data = {}
            confidence_scores = {}
            total_confidence = 0
            found_fields = 0
            
            for field_id, result in semantic_results.items():
                if result.extracted_value:
                    extracted_data[field_id] = result.extracted_value
                    confidence_scores[field_id] = result.confidence
                    total_confidence += result.confidence
                    found_fields += 1
            
            if not extracted_data:
                return self._handle_extraction_error(state, "Semantic extraction failed - no field values found")
            
            average_confidence = total_confidence / found_fields if found_fields > 0 else 0.0
            
            # Create extraction result object for compatibility
            extraction_result = {
                "extracted_data": extracted_data,
                "confidence_score": average_confidence,
                "field_confidence_scores": confidence_scores,
                "extraction_methods": {field_id: result.extraction_method for field_id, result in semantic_results.items()},
                "total_fields": len(semantic_results),
                "found_fields": found_fields
            }
            
            # Save extraction results
            await self._save_semantic_extraction_json(extraction_result, files_to_process)
            
            # Update state with results
            state.extracted_data = extracted_data
            state.extraction_confidence = average_confidence
            
            # Add results to conversation
            file_list = [os.path.basename(f) for f in files_to_process]
            high_confidence_fields = [field for field, confidence in confidence_scores.items() if confidence >= 0.8]
            
            state.messages.append({
                "role": "assistant", 
                "content": f"✅ Semantic data extraction completed.\n"
                          f"   📄 Processed files: {', '.join(file_list)}\n"
                          f"   🎯 Extracted {found_fields}/{len(semantic_results)} fields with {average_confidence:.0%} average confidence\n"
                          f"   🏆 High confidence fields ({len(high_confidence_fields)}): {', '.join(high_confidence_fields[:5])}{'...' if len(high_confidence_fields) > 5 else ''}\n"
                          f"   📊 Field types found: {len(set(req.field_type for req in extraction_requests))} types",
                "agent": self.agent_type.value,
                "extraction_result": extraction_result
            })
            
            # Move to next step
            state.current_step = "reviewing_extraction"
            state.current_agent = AgentType.ORCHESTRATOR
            
            return state
            
        except Exception as e:
            return self._handle_extraction_error(state, f"Semantic extraction error: {str(e)}")
    
    def _create_extraction_requests_from_form_structure(self, form_structure: Dict[str, Any]) -> List[FieldExtractionRequest]:
        """Create extraction requests from form structure learned by form_learner agent."""
        extraction_requests = []
        
        try:
            # Extract sections from form structure
            sections = form_structure.get('sections', [])
            
            for section in sections:
                section_name = section.get('name', 'Unknown Section')
                fields = section.get('fields', [])
                
                print(f"📋 Processing section '{section_name}' with {len(fields)} fields")
                
                for field in fields:
                    field_id = field.get('id', '')
                    field_name = field.get('name', field_id)
                    field_type = self._determine_field_type(field)
                    is_required = field.get('required', False)
                    description = field.get('description', '')
                    field_context = field.get('context', '')
                    
                    if field_id and field_name:
                        # Use the specific field context from form structure, fallback to section info
                        context_info = field_context if field_context else f"Section: {section_name}"
                        
                        request = FieldExtractionRequest(
                            field_id=field_id,
                            field_name=field_name,
                            field_type=field_type,
                            section_id=section.get('id', section_name),
                            required=is_required,
                            description=description,
                            context=context_info
                        )
                        extraction_requests.append(request)
                        
            print(f"🎯 Created {len(extraction_requests)} extraction requests from form structure")
            return extraction_requests
            
        except Exception as e:
            print(f"❌ Error creating extraction requests: {str(e)}")
            return []
    
    def _determine_field_type(self, field: Dict[str, Any]) -> str:
        """Determine field type from form field information."""
        field_type = field.get('type', 'text')
        field_name = field.get('name', '').lower()
        field_id = field.get('id', '').lower()
        
        # Map form field types to extraction field types
        if field_type in ['date', 'datetime']:
            return 'date'
        elif field_type in ['email']:
            return 'email'
        elif field_type in ['tel', 'phone']:
            return 'phone'
        elif field_type in ['number', 'numeric']:
            return 'number'
        elif field_type in ['checkbox', 'radio']:
            return 'boolean'
        elif 'name' in field_name or 'name' in field_id:
            return 'name'
        elif 'date' in field_name or 'date' in field_id:
            return 'date'
        elif 'email' in field_name or 'email' in field_id:
            return 'email'
        elif 'phone' in field_name or 'tel' in field_name or 'phone' in field_id:
            return 'phone'
        elif 'address' in field_name or 'address' in field_id:
            return 'address'
        else:
            return 'text'
    
    async def _save_semantic_extraction_json(self, extraction_result: Any, processed_files: List[str]) -> None:
        """Save semantic extraction results to JSON file."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"semantic_extraction_{timestamp}.json"
            filepath = os.path.join("output", filename)
            
            # Create output directory if it doesn't exist
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # Prepare data for JSON serialization
            # Handle both dict and object formats for extraction_result
            if isinstance(extraction_result, dict):
                extracted_data = extraction_result.get("extracted_data", {})
                confidence_score = extraction_result.get("confidence_score", 0.0)
                field_confidence_scores = extraction_result.get("field_confidence_scores", {})
                extraction_methods = extraction_result.get("extraction_methods", {})
            else:
                # Object format (for compatibility)
                extracted_data = getattr(extraction_result, 'extracted_data', {})
                confidence_score = getattr(extraction_result, 'confidence_score', 0.0)
                field_confidence_scores = getattr(extraction_result, 'field_confidence_scores', {})
                extraction_methods = getattr(extraction_result, 'extraction_methods', {})
            
            output_data = {
                "timestamp": timestamp,
                "processed_files": [os.path.basename(f) for f in processed_files],
                "extracted_data": extracted_data,
                "confidence_score": confidence_score,
                "field_confidence_scores": field_confidence_scores,
                "extraction_methods": extraction_methods,
                "total_fields": len(extracted_data),
                "high_confidence_fields": [
                    field for field, confidence in field_confidence_scores.items() 
                    if confidence >= 0.8
                ]
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 Semantic extraction results saved to: {filepath}")
            
        except Exception as e:
            print(f"❌ Error saving semantic extraction JSON: {str(e)}")
    
    def _handle_extraction_error(self, state: AgentState, error_message: str) -> AgentState:
        """Handle extraction errors and update state accordingly."""
        print(f"❌ Data Extraction Error: {error_message}")
        
        # Add error message to conversation
        state.messages.append({
            "role": "assistant",
            "content": f"❌ Data extraction failed: {error_message}\n"
                      f"   Please check the input documents and try again.",
            "agent": self.agent_type.value
        })
        
        # Set error state
        state.current_step = "extraction_error"
        state.current_agent = AgentType.ORCHESTRATOR
        
        return state
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
