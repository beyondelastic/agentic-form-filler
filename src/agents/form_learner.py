"""Form Learning Agent that analyzes and understands form structure before data extraction.

This agent serves as the first step in the form filling workflow, analyzing the target 
form to understand its complete structure, sections, fields, requirements, and context. 
This is then used by subsequent agents for more intelligent data extraction 
and form filling.
"""

import os
import json
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

from src.models import AgentState, AgentType
from src.tools.comprehensive_form_analyzer import ComprehensiveFormAnalysisTool, FormStructure
from src.tools.comprehensive_excel_form_analyzer import ComprehensiveExcelFormAnalyzer, ExcelFormStructure
from src.llm_client import get_llm_client


class FormLearningAgent:
    """
    Form Learning Agent that:
    1. Analyzes the structure of target forms comprehensively  
    2. Understands sections, fields, requirements, and context
    3. Identifies field relationships and dependencies
    4. Provides structured form knowledge for other agents
    5. Saves analysis results for reuse
    """
    
    def __init__(self):
        self.agent_type = AgentType.FORM_LEARNER  # Will need to add this to enum
        self.pdf_form_analyzer = ComprehensiveFormAnalysisTool()
        self.excel_form_analyzer = ComprehensiveExcelFormAnalyzer()
        self.llm_client = get_llm_client()
        self.analysis_cache = {}  # Cache form analyses to avoid re-processing
    
    def _format_field(self, field, all_fields_dict=None):
        """Handle different field structures for PDF vs Excel."""
        if isinstance(field, str) and all_fields_dict:
            # Excel field (field ID string, need to lookup in all_fields)
            field_data = all_fields_dict.get(field, None)
            if field_data:
                # field_data is an ExcelFormField object, use safe_get_attr
                return {
                    "id": self._safe_get_attr(field_data, 'id', field),
                    "name": self._safe_get_attr(field_data, 'name', ''),
                    "type": self._safe_get_attr(field_data, 'field_type', 'text'),
                    "required": self._safe_get_attr(field_data, 'required', False),
                    "description": self._safe_get_attr(field_data, 'description', ''),
                    "context": self._safe_get_attr(field_data, 'context', '')
                }
            else:
                # Fallback if field not found
                return {
                    "id": field,
                    "name": field,
                    "type": "text",
                    "required": False,
                    "description": "",
                    "context": ""
                }
        elif isinstance(field, dict):
            # Excel field (already a dict)
            return {
                "id": field.get("id", "unknown"),
                "name": field.get("name", ""),
                "type": field.get("field_type", field.get("type", "text")),
                "required": field.get("required", False),
                "description": field.get("description", ""),
                "context": field.get("context", "")
            }
        else:
            # PDF or Excel field object with attributes
            return {
                "id": self._safe_get_attr(field, 'id', 'unknown'),
                "name": self._safe_get_attr(field, 'name', ''),
                "type": self._safe_get_attr(field, 'field_type', 'text'),
                "required": self._safe_get_attr(field, 'required', False),
                "description": self._safe_get_attr(field, 'description', ''),
                "context": self._safe_get_attr(field, 'context', '')
            }

    def _convert_all_fields_to_dict(self, all_fields):
        """Convert all_fields to a dictionary format preserving Excel-specific properties."""
        if isinstance(all_fields, dict):
            # Already a dict, convert each field to preserve all properties
            result = {}
            for field_id, field_data in all_fields.items():
                if isinstance(field_data, dict):
                    result[field_id] = field_data
                else:
                    # Convert field object to dict, preserving Excel properties
                    result[field_id] = {
                        "id": self._safe_get_attr(field_data, 'id', field_id),
                        "name": self._safe_get_attr(field_data, 'name', ''),
                        "field_type": self._safe_get_attr(field_data, 'field_type', 'text'),
                        "required": self._safe_get_attr(field_data, 'required', False),
                        "description": self._safe_get_attr(field_data, 'description', ''),
                        "context": self._safe_get_attr(field_data, 'context', ''),
                        # Preserve Excel-specific properties
                        "cell_address": self._safe_get_attr(field_data, 'cell_address', ''),
                        "worksheet": self._safe_get_attr(field_data, 'worksheet', 'Sheet1'),
                        "position": self._safe_get_attr(field_data, 'position', {}),
                        "named_range": self._safe_get_attr(field_data, 'named_range', None),
                        "section_id": self._safe_get_attr(field_data, 'section_id', ''),
                        "dependencies": self._safe_get_attr(field_data, 'dependencies', []),
                        "validation_rules": self._safe_get_attr(field_data, 'validation_rules', []),
                        "default_value": self._safe_get_attr(field_data, 'default_value', None),
                        "options": self._safe_get_attr(field_data, 'options', [])
                    }
            return result
        return {}

    async def process(self, state: AgentState) -> AgentState:
        """Process form learning and analysis."""
        print(f"\n📚 Form Learning Agent Processing")
        
        try:
            # Check if we have a form template to analyze
            if not state.form_template_path:
                return self._handle_learning_error(state, "No form template path provided")
            
            if not os.path.exists(state.form_template_path):
                return self._handle_learning_error(state, f"Form template not found: {state.form_template_path}")
            
            print(f"🎯 Analyzing target form: {os.path.basename(state.form_template_path)}")
            
            # Analyze the form based on its type (PDF or Excel)
            form_structure = await self._analyze_form_by_type(state.form_template_path)
            
            if form_structure is None:
                return self._handle_learning_error(state, "Failed to analyze form structure")
            
            # Update state with form learning results
            return await self._update_state_with_learning_results(state, form_structure)
            
        except Exception as e:
            return self._handle_learning_error(state, f"Error in form learning: {str(e)}")

    async def _analyze_form_by_type(self, file_path: str) -> Optional[Union[FormStructure, ExcelFormStructure]]:
        """Analyze form based on file type (PDF or Excel)."""
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Check cache first
        cache_key = self._get_cache_key(file_path)
        if cache_key in self.analysis_cache:
            print(f"📋 Using cached analysis for: {os.path.basename(file_path)}")
            return self.analysis_cache[cache_key]
        
        try:
            if file_ext == '.pdf':
                print(f"📄 Analyzing PDF form: {os.path.basename(file_path)}")
                result = await self.pdf_form_analyzer.analyze_form_structure(file_path)
            elif file_ext in ['.xlsx', '.xls']:
                print(f"📊 Analyzing Excel form: {os.path.basename(file_path)}")
                result = await self.excel_form_analyzer.analyze_excel_form_structure(file_path)
            else:
                print(f"❌ Unsupported file type: {file_ext}")
                return None
                
            # Cache the result
            if result:
                self.analysis_cache[cache_key] = result
                
            return result
            
        except Exception as e:
            print(f"❌ Error analyzing form: {str(e)}")
            return None

    def _safe_get_attr(self, obj, attr, default=''):
        """Safely get attribute from object or dict."""
        if hasattr(obj, attr):
            return getattr(obj, attr)
        elif isinstance(obj, dict):
            return obj.get(attr, default)
        else:
            return default

    async def _update_state_with_learning_results(self, state: AgentState, form_structure: Union[FormStructure, ExcelFormStructure]) -> AgentState:
        """Update the state with comprehensive form learning results."""
        
        # Update state - form learning complete, route to data extraction
        state.current_agent = AgentType.DATA_EXTRACTOR
        state.current_step = "data_extraction"
        
        state.form_fields = {field_id: {
            "name": self._safe_get_attr(field, 'name', ''),
            "type": self._safe_get_attr(field, 'field_type', 'text'),
            "required": self._safe_get_attr(field, 'required', False),
            "section": self._safe_get_attr(field, 'section_id', ''),
            "context": self._safe_get_attr(field, 'context', ''),
            "description": self._safe_get_attr(field, 'description', '')
        } for field_id, field in form_structure.all_fields.items()}
        
        state.field_types = {field_id: self._safe_get_attr(field, 'field_type', 'text')
                           for field_id, field in form_structure.all_fields.items()}
        state.required_fields = [field_id for field_id, field in form_structure.all_fields.items() 
                               if self._safe_get_attr(field, 'required', False)]
        state.form_analysis_confidence = 0.95  # High confidence for comprehensive analysis
        
        # Create learning summary with enhanced guidance
        learning_summary = self._create_enhanced_learning_summary(form_structure)
        
        # Store form structure for data extractor and form filler
        form_data = {
            "sections": [{
                "id": s.id,
                "name": s.title,
                "title": s.title,
                "description": s.description,
                "fields": [self._format_field(field, form_structure.all_fields) for field in s.fields]
            } for s in form_structure.sections],
            "total_fields": len(form_structure.all_fields),
            "field_relationships": form_structure.field_relationships,
            "instructions": form_structure.instructions,
            "warnings": form_structure.warnings
        }
        
        # Create LLM-friendly summary for intelligent agents
        try:
            summary_prompt = f"""
Based on this comprehensive form structure analysis, create a concise summary for AI agents:

Form: {form_structure.title}
Purpose: {form_structure.purpose}
Total Fields: {len(form_structure.all_fields)}
Required Fields: {len(state.required_fields)}

Sections and Fields:
{self._format_sections_for_summary(form_structure.sections)}

Key Requirements:
- Focus on required fields first: {', '.join(state.required_fields[:5])}
- Form language: {getattr(form_structure, 'language', 'unknown')}
- Special instructions: {'; '.join(form_structure.instructions[:3]) if form_structure.instructions else 'None'}

Create a brief, actionable summary for data extraction and form filling agents.
"""
            
            messages = self.llm_client.create_messages(
                system_prompt="You are an AI assistant that creates concise summaries for form analysis.",
                user_message=summary_prompt
            )
            response_msg = await self.llm_client.invoke(messages)
            response = response_msg.content
            
            if response and response.strip():
                try:
                    learning_summary["llm_guidance"] = json.loads(response) if response.startswith('{') else {"summary": response}
                except json.JSONDecodeError:
                    learning_summary["llm_guidance"] = {"summary": response}
            
        except Exception as e:
            print(f"⚠️ Error creating learning summary: {str(e)}")
            learning_summary["llm_guidance"] = {"summary": "Form analysis completed successfully"}
        
        # Store enhanced learning results
        state.form_learning_summary = learning_summary
        
        # Save analysis results to JSON file
        self._save_analysis_results(state, form_structure)
        
        # Add new form learning data to state
        # Store form structure for data extractor
        state.form_structure = {
            "title": form_structure.title,
            "purpose": form_structure.purpose,
            "sections": [{
                "id": s.id,
                "name": s.title,
                "title": s.title,
                "description": s.description,
                "fields": [self._format_field(field, form_structure.all_fields) for field in s.fields]
            } for s in form_structure.sections],
            "total_fields": len(form_structure.all_fields),
            "field_relationships": form_structure.field_relationships,
            "instructions": form_structure.instructions,
            "warnings": form_structure.warnings,
            # CRITICAL: Preserve complete field definitions for Excel form filler
            "all_fields": self._convert_all_fields_to_dict(form_structure.all_fields) if hasattr(form_structure, 'all_fields') else {}
        }
        
        # Also store in messages for logging
        state.messages.append({
            "type": "form_learning_complete",
            "sender": "form_learner",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "form_structure": state.form_structure,
                "learning_summary": learning_summary
            }
        })
        
        return state

    def _create_enhanced_learning_summary(self, form_structure: Union[FormStructure, ExcelFormStructure]) -> Dict[str, Any]:
        """Create enhanced learning summary with strategic guidance."""
        return {
            "analysis_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_sections": len(form_structure.sections),
                "total_fields": len(form_structure.all_fields),
                "required_fields_count": len([f for f in form_structure.all_fields.values() 
                                           if self._safe_get_attr(f, 'required', False)]),
                "form_complexity": "high" if len(form_structure.all_fields) > 50 else "medium" if len(form_structure.all_fields) > 20 else "low",
                "language": getattr(form_structure, 'language', 'unknown'),
                "form_type": type(form_structure).__name__
            },
            "strategic_insights": {
                "key_requirements": ["Valid employment offer", "Personal identification", "Employer information"]
            },
            "section_guide": {
                section.id: {
                    "purpose": section.description or section.title,
                    "key_fields": [str(field)[:20] for field in list(section.fields)[:3]],  # First 3 fields as strings
                    "completion_strategy": f"Complete all fields in {section.title}"
                } for section in form_structure.sections
            },
            "field_mapping_hints": {
                "common_data_to_field_mapping": {
                    "person_name": ["name", "nachname", "vorname", "first_name", "last_name"],
                    "birth_date": ["birth", "geburt", "dob", "birthday"],
                    "nationality": ["nationality", "staatsangehörigkeit", "country"],
                    "employer_name": ["employer", "arbeitgeber", "company"],
                    "job_title": ["job", "position", "stelle", "beruf"]
                }
            },
            "filling_priorities": {
                "critical_fields": [field_id for field_id, field in form_structure.all_fields.items() 
                                  if self._safe_get_attr(field, 'required', False)],
                "optional_fields": [field_id for field_id, field in form_structure.all_fields.items() 
                                  if not self._safe_get_attr(field, 'required', False)],
                "validation_notes": form_structure.warnings if hasattr(form_structure, 'warnings') else []
            }
        }

    def _format_sections_for_summary(self, sections: List) -> str:
        """Format sections for LLM summary."""
        formatted = []
        for section in sections:
            field_count = len(section.fields) if hasattr(section.fields, '__len__') else 0
            formatted.append(f"Section {section.id}: {section.title}")
            formatted.append(f"  - Fields: {field_count}")
            formatted.append(f"  - Description: {section.description or 'N/A'}")
        return "\n".join(formatted)

    def _get_cache_key(self, file_path: str) -> str:
        """Generate cache key for form analysis."""
        try:
            stat = os.stat(file_path)
            return f"{file_path}_{stat.st_mtime}_{stat.st_size}"
        except:
            return file_path

    def _save_analysis_results(self, state: AgentState, form_structure: Union[FormStructure, ExcelFormStructure]) -> None:
        """Save detailed analysis results to output directory."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"./output/form_learning_{timestamp}.json"
            
            # Create output directory if needed
            os.makedirs("./output", exist_ok=True)
            
            # Save using the form analyzer's save method
            if isinstance(form_structure, ExcelFormStructure):
                self.excel_form_analyzer.save_analysis_result(form_structure, output_path)
            else:
                self.pdf_form_analyzer.save_analysis_result(form_structure, output_path)
            
            print(f"💾 Form learning results saved: {output_path}")
            
        except Exception as e:
            print(f"⚠️ Could not save form learning results: {str(e)}")

    def _handle_learning_error(self, state: AgentState, error_message: str) -> AgentState:
        """Handle errors during form learning."""
        print(f"❌ Form learning error: {error_message}")
        
        state.messages.append({
            "type": "form_learning_error",
            "sender": "form_learner",
            "timestamp": datetime.now().isoformat(),
            "error": error_message
        })
        
        # Set flag for human review
        state.requires_human_review = True
        
        return state

    def get_form_guidance(self, form_template_path: str) -> Optional[Dict[str, Any]]:
        """Get form guidance for a specific form (utility method)."""
        cache_key = self._get_cache_key(form_template_path)
        if cache_key in self.analysis_cache:
            form_structure = self.analysis_cache[cache_key]
            # Return a basic guidance structure
            return {
                "sections": len(form_structure.sections),
                "fields": len(form_structure.all_fields),
                "required_fields": len([f for f in form_structure.all_fields.values() 
                                      if self._safe_get_attr(f, 'required', False)]),
                "field_types": {fid: self._safe_get_attr(f, 'field_type', 'text') 
                              for fid, f in form_structure.all_fields.items()}
            }
        return None