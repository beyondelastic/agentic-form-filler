"""Comprehensive form analysis tool for understanding document structure and context.

This tool goes beyond simple key-value extraction to understand the complete 
structure of forms including sections, instructions, field relationships,
and contextual information needed for intelligent form filling.
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import pdfplumber
import fitz  # PyMuPDF for extracting real PDF form fields

from src.config import config
from src.llm_client import get_llm_client


@dataclass
class FormSection:
    """Represents a section of the form (A, B, C, etc.)."""
    id: str
    title: str
    description: Optional[str]
    instructions: List[str]
    fields: List[Dict[str, Any]]
    subsections: List['FormSection']
    page_number: int
    position: Dict[str, float]  # x, y, width, height


@dataclass
class FormField:
    """Represents a single field in the form."""
    id: str
    name: str
    description: Optional[str]
    field_type: str  # text, checkbox, radio, dropdown, date, etc.
    required: bool
    section_id: str
    dependencies: List[str]  # Other field IDs this field depends on
    validation_rules: List[str]
    default_value: Optional[str]
    options: Optional[List[str]]  # For dropdowns, radio buttons
    position: Dict[str, float]
    context: str  # Surrounding text that provides context


@dataclass
class FormStructure:
    """Complete form structure analysis."""
    title: str
    description: str
    purpose: str
    sections: List[FormSection]
    all_fields: Dict[str, FormField]
    field_relationships: Dict[str, List[str]]
    instructions: List[str]
    warnings: List[str]
    legal_notes: List[str]
    total_pages: int
    language: str
    form_version: Optional[str]
    issuing_authority: Optional[str]


class ComprehensiveFormAnalysisTool:
    """Tool for comprehensive form structure analysis and learning."""
    
    def __init__(self):
        """Initialize the comprehensive form analysis tool."""
        self.azure_client = None
        self.llm_client = get_llm_client()
        self._initialize_azure_client()
    
    def _initialize_azure_client(self):
        """Initialize Azure Document Intelligence client if available."""
        try:
            if config.has_document_intelligence():
                endpoint, key = config.get_azure_doc_intelligence_credentials()
                self.azure_client = DocumentAnalysisClient(
                    endpoint=endpoint,
                    credential=AzureKeyCredential(key)
                )
                print("✅ Azure Document Intelligence initialized for comprehensive analysis")
            else:
                print("⚠️ Azure Document Intelligence not configured - using fallback methods")
        except Exception as e:
            print(f"⚠️ Failed to initialize Azure Document Intelligence: {str(e)}")
            self.azure_client = None
    
    async def analyze_form_structure(self, file_path: str) -> FormStructure:
        """
        Analyze the complete structure of a form document.
        
        Args:
            file_path: Path to the PDF form file
            
        Returns:
            FormStructure with comprehensive analysis
        """
        print(f"🔍 Starting comprehensive form analysis: {os.path.basename(file_path)}")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Form file not found: {file_path}")
        
        # Step 1: Extract raw document content with multiple methods
        raw_content = self._extract_raw_content(file_path)
        
        # Step 2: Extract real PDF form field names and metadata
        pdf_fields = self._extract_pdf_form_fields(file_path)
        
        # Step 3: Analyze document structure with Azure if available
        azure_analysis = None
        if self.azure_client:
            azure_analysis = self._analyze_with_azure(file_path)
        
        # Step 4: Extract text and layout with pdfplumber
        text_analysis = self._analyze_with_pdfplumber(file_path)
        
        # Step 5: Use LLM to understand structure and create comprehensive analysis
        # If LLM consistently fails, we can fall back to PDF-only analysis
        try:
            form_structure = await self._analyze_structure_with_llm(
                raw_content, azure_analysis, text_analysis, file_path, pdf_fields
            )
        except Exception as e:
            print(f"⚠️ LLM analysis failed completely: {str(e)}")
            print("🔄 Falling back to PDF-only structure analysis...")
            form_structure = self._create_pdf_only_structure(raw_content, pdf_fields, file_path)
        
        print(f"✅ Comprehensive analysis complete: {len(form_structure.sections)} sections, {len(form_structure.all_fields)} fields")
        return form_structure
    
    def _extract_raw_content(self, file_path: str) -> Dict[str, Any]:
        """Extract raw content using multiple methods."""
        print("📄 Extracting raw content...")
        
        content = {
            "file_name": os.path.basename(file_path),
            "text_content": "",
            "pages": [],
            "metadata": {}
        }
        
        try:
            with pdfplumber.open(file_path) as pdf:
                content["metadata"] = {
                    "total_pages": len(pdf.pages),
                    "creator": pdf.metadata.get("Creator"),
                    "producer": pdf.metadata.get("Producer"),
                    "title": pdf.metadata.get("Title"),
                    "subject": pdf.metadata.get("Subject")
                }
                
                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text() or ""
                    content["text_content"] += f"\n=== PAGE {page_num} ===\n{page_text}"
                    
                    # Extract tables if present
                    tables = page.extract_tables()
                    
                    content["pages"].append({
                        "page_number": page_num,
                        "text": page_text,
                        "tables": tables,
                        "width": page.width,
                        "height": page.height
                    })
        
        except Exception as e:
            print(f"⚠️ Error extracting raw content: {str(e)}")
            content["text_content"] = "Error extracting content"
        
        return content
    
    def _extract_pdf_form_fields(self, file_path: str) -> Dict[str, Dict[str, Any]]:
        """Extract real PDF form field names and metadata using PyMuPDF."""
        pdf_fields = {}
        
        try:
            doc = fitz.open(file_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Get form fields (widgets) on this page
                widgets = page.widgets()
                
                for widget in widgets:
                    field_name = widget.field_name
                    field_type = widget.field_type
                    field_rect = widget.rect
                    field_value = widget.field_value
                    
                    # Get field type as string
                    field_type_map = {
                        1: "text",
                        2: "button", 
                        3: "choice",
                        4: "signature"
                    }
                    
                    field_type_str = field_type_map.get(field_type, "unknown")
                    
                    if field_name and field_name not in pdf_fields:
                        pdf_fields[field_name] = {
                            "field_name": field_name,
                            "field_type": field_type_str,
                            "page_number": page_num + 1,
                            "position": {
                                "x": field_rect.x0,
                                "y": field_rect.y0,
                                "width": field_rect.width,
                                "height": field_rect.height
                            },
                            "current_value": field_value,
                            "is_required": getattr(widget, 'field_flags', 0) & 2 > 0,  # Required flag
                            "is_readonly": getattr(widget, 'field_flags', 0) & 1 > 0   # ReadOnly flag
                        }
            
            doc.close()
            print(f"📋 Extracted {len(pdf_fields)} PDF form fields with real names")
            
        except Exception as e:
            print(f"⚠️ Error extracting PDF form fields: {str(e)}")
        
        return pdf_fields
    
    def _analyze_with_azure(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Analyze document with Azure Document Intelligence for detailed structure."""
        if not self.azure_client:
            return None
        
        print("☁️ Analyzing with Azure Document Intelligence...")
        
        try:
            with open(file_path, "rb") as f:
                poller = self.azure_client.begin_analyze_document("prebuilt-layout", f)
                result = poller.result()
            
            # Extract comprehensive information
            analysis = {
                "pages": [],
                "tables": [],
                "paragraphs": [],
                "lines": [],
                "words": [],
                "selection_marks": []
            }
            
            # Process pages
            for page in result.pages:
                page_info = {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                    "unit": page.unit,
                    "lines": []
                }
                
                # Extract lines with position information
                for line in page.lines:
                    line_info = {
                        "content": line.content,
                        "polygon": [{"x": point.x, "y": point.y} for point in line.polygon] if line.polygon else []
                    }
                    page_info["lines"].append(line_info)
                
                # Extract selection marks (checkboxes, radio buttons)
                for mark in page.selection_marks:
                    mark_info = {
                        "state": mark.state,
                        "polygon": [{"x": point.x, "y": point.y} for point in mark.polygon] if mark.polygon else []
                    }
                    
                    # Add confidence if available (not all mark types have this attribute)
                    if hasattr(mark, 'confidence') and mark.confidence is not None:
                        mark_info["confidence"] = mark.confidence
                    
                    analysis["selection_marks"].append(mark_info)
                
                analysis["pages"].append(page_info)
            
            # Extract tables with detailed structure
            for table in result.tables:
                table_info = {
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cells": []
                }
                
                for cell in table.cells:
                    cell_info = {
                        "content": cell.content,
                        "row_index": cell.row_index,
                        "column_index": cell.column_index,
                        "row_span": cell.row_span,
                        "column_span": cell.column_span,
                    }
                    
                    # Add confidence if available (not all cell types have this attribute)
                    if hasattr(cell, 'confidence') and cell.confidence is not None:
                        cell_info["confidence"] = cell.confidence
                    
                    table_info["cells"].append(cell_info)
                
                analysis["tables"].append(table_info)
            
            # Extract paragraphs
            for para in result.paragraphs:
                para_info = {
                    "content": para.content,
                    "role": para.role if hasattr(para, 'role') else None
                }
                analysis["paragraphs"].append(para_info)
            
            return analysis
        
        except Exception as e:
            print(f"⚠️ Error in Azure analysis: {str(e)}")
            return None
    
    def _analyze_with_pdfplumber(self, file_path: str) -> Dict[str, Any]:
        """Analyze document with pdfplumber for text layout and structure."""
        print("📝 Analyzing with pdfplumber...")
        
        analysis = {
            "text_blocks": [],
            "tables": [],
            "form_elements": [],
            "layout_info": {}
        }
        
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract text with coordinates
                    chars = page.chars
                    words = page.extract_words()
                    
                    # Group text into logical blocks
                    text_blocks = self._group_text_into_blocks(words)
                    analysis["text_blocks"].extend([
                        {**block, "page": page_num} for block in text_blocks
                    ])
                    
                    # Extract tables
                    tables = page.extract_tables()
                    for i, table in enumerate(tables):
                        analysis["tables"].append({
                            "page": page_num,
                            "table_index": i,
                            "data": table
                        })
                    
                    # Try to identify form elements (checkboxes, form fields)
                    form_elements = self._identify_form_elements(page, words)
                    analysis["form_elements"].extend([
                        {**element, "page": page_num} for element in form_elements
                    ])
        
        except Exception as e:
            print(f"⚠️ Error in pdfplumber analysis: {str(e)}")
        
        return analysis
    
    def _group_text_into_blocks(self, words: List[Dict]) -> List[Dict[str, Any]]:
        """Group words into logical text blocks."""
        if not words:
            return []
        
        blocks = []
        current_block = {
            "text": "",
            "x0": float('inf'),
            "y0": float('inf'),
            "x1": 0,
            "y1": 0,
            "words": []
        }
        
        # Simple grouping by proximity
        for word in words:
            if not current_block["words"] or self._words_are_close(current_block["words"][-1], word):
                current_block["words"].append(word)
                current_block["text"] += (" " if current_block["text"] else "") + word["text"]
                current_block["x0"] = min(current_block["x0"], word["x0"])
                current_block["y0"] = min(current_block["y0"], word["top"])
                current_block["x1"] = max(current_block["x1"], word["x1"])
                current_block["y1"] = max(current_block["y1"], word["bottom"])
            else:
                if current_block["text"].strip():
                    blocks.append(current_block)
                current_block = {
                    "text": word["text"],
                    "x0": word["x0"],
                    "y0": word["top"],
                    "x1": word["x1"],
                    "y1": word["bottom"],
                    "words": [word]
                }
        
        if current_block["text"].strip():
            blocks.append(current_block)
        
        return blocks
    
    def _words_are_close(self, word1: Dict, word2: Dict, threshold: float = 20) -> bool:
        """Check if two words are close enough to be in the same text block."""
        vertical_distance = abs(word1["top"] - word2["top"])
        horizontal_gap = word2["x0"] - word1["x1"]
        
        # Words are close if they're on similar vertical level and not too far apart
        return vertical_distance < threshold and horizontal_gap < threshold * 3
    
    def _identify_form_elements(self, page, words: List[Dict]) -> List[Dict[str, Any]]:
        """Identify potential form elements like checkboxes, input fields."""
        form_elements = []
        
        # Look for checkbox patterns
        text_content = page.extract_text() or ""
        
        # Simple patterns for checkboxes
        checkbox_patterns = ['☐', '□', '☑', '☒', '_____', '____']
        
        for pattern in checkbox_patterns:
            if pattern in text_content:
                # Find locations - this is a simplified approach
                form_elements.append({
                    "type": "checkbox" if pattern in ['☐', '□', '☑', '☒'] else "input_field",
                    "pattern": pattern,
                    "count": text_content.count(pattern)
                })
        
        return form_elements
    
    async def _analyze_structure_with_llm(
        self,
        raw_content: Dict[str, Any],
        azure_analysis: Optional[Dict[str, Any]],
        text_analysis: Dict[str, Any],
        file_path: str,
        pdf_fields: Dict[str, Dict[str, Any]]
    ) -> FormStructure:
        """Use LLM to analyze and understand the form structure."""
        print("🤖 Analyzing form structure with LLM...")
        
        # Prepare comprehensive prompt for LLM analysis
        analysis_prompt = self._build_analysis_prompt(raw_content, azure_analysis, text_analysis, pdf_fields)
        
        try:
            # Create messages for LLM
            messages = self.llm_client.create_messages(
                "You are an expert form analyst. Analyze documents comprehensively.",
                analysis_prompt
            )
            
            # Get response from LLM
            response = await self.llm_client.invoke(messages)
            response_text = response.content
            
            # Parse LLM response into structured format
            structure_data = self._parse_llm_response(response_text)
            
            # Create FormStructure object
            form_structure = self._create_form_structure(structure_data, file_path)
            
            # Enhance with real PDF fields to ensure completeness
            form_structure = self._enhance_with_pdf_fields(form_structure, pdf_fields)
            
            return form_structure
        
        except Exception as e:
            print(f"❌ Error in LLM analysis: {str(e)}")
            # Return a basic structure as fallback
            return self._create_fallback_structure(raw_content, file_path)
    
    def _build_analysis_prompt(
        self,
        raw_content: Dict[str, Any],
        azure_analysis: Optional[Dict[str, Any]],
        text_analysis: Dict[str, Any],
        pdf_fields: Dict[str, Dict[str, Any]]
    ) -> str:
        """Build a comprehensive prompt for LLM analysis."""
        
        # Build PDF fields summary for the prompt
        pdf_fields_info = ""
        if pdf_fields:
            pdf_fields_info = f"\n\nREAL PDF FORM FIELDS DETECTED ({len(pdf_fields)} fields):\n"
            for field_name, field_info in pdf_fields.items():
                pdf_fields_info += f"- {field_name} ({field_info['field_type']}) on page {field_info['page_number']}\n"
        
        # Limit PDF fields info to prevent overly long prompts
        pdf_fields_sample = ""
        if pdf_fields:
            field_sample = list(pdf_fields.items())[:20]  # Show only first 20 fields as examples
            pdf_fields_sample = f"\n\nSAMPLE PDF FIELD NAMES ({len(field_sample)} of {len(pdf_fields)} total):\n"
            for field_name, field_info in field_sample:
                pdf_fields_sample += f"- {field_name} ({field_info['field_type']})\n"
            if len(pdf_fields) > 20:
                pdf_fields_sample += f"... and {len(pdf_fields) - 20} more fields available"

        prompt = f"""
Analyze this German employment authorization form. Return ONLY valid JSON (no markdown, no explanations).

FORM TEXT (excerpt):
{raw_content.get('text_content', '')[:4000]}
{pdf_fields_sample}

CRITICAL JSON RULES:
1. Return ONLY the JSON object, no other text
2. Use double quotes for all strings
3. Escape quotes in text with \"
4. No trailing commas
5. Use real PDF field names as field IDs where possible

JSON Structure Required:
{{
    "title": "Erklärung zum Beschäftigungsverhältnis",
    "description": "Employment authorization form",
    "purpose": "Employment verification and documentation",
    "issuing_authority": "Authority name",
    "language": "de",
    "sections": [
        {{
            "id": "SECTION_A",
            "title": "Personal Information",
            "description": "Employee personal details",
            "instructions": [],
            "fields": [
                {{
                    "id": "form_field_first_name",
                    "name": "First Name", 
                    "type": "text",
                    "required": true,
                    "context": "Employee first name field"
                }}
            ]
        }}
    ],
    "general_instructions": ["Complete all required fields"],
    "warnings": ["Ensure accuracy of information"],
    "legal_notes": ["Legal compliance required"]
}}
"""
        
        if azure_analysis:
            prompt += f"\n\nADDITIONAL AZURE ANALYSIS DATA:\nTables found: {len(azure_analysis.get('tables', []))}\nSelection marks: {len(azure_analysis.get('selection_marks', []))}"
        
        return prompt
    
    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured data with robust error handling."""
        try:
            # Try to extract JSON from response
            import re
            
            # First try direct JSON parsing on cleaned response
            cleaned_response = response.strip()
            try:
                return json.loads(cleaned_response)
            except json.JSONDecodeError:
                pass
            
            # Try to extract JSON block from markdown
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Look for any JSON-like structure
                json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    print("⚠️ Could not find valid JSON structure in LLM response")
                    return self._create_fallback_from_text(response)
            
            # Aggressive JSON cleanup
            json_str = self._clean_json_string(json_str)
            
            return json.loads(json_str)
            
        except json.JSONDecodeError as e:
            print(f"⚠️ Error parsing LLM JSON response: {str(e)}")
            print(f"⚠️ Response length: {len(response)} chars")
            # Show a snippet of the problematic area
            error_pos = getattr(e, 'pos', 0)
            start_pos = max(0, error_pos - 50)
            end_pos = min(len(response), error_pos + 50)
            snippet = response[start_pos:end_pos]
            print(f"⚠️ Error near: ...{snippet}...")
            return self._create_fallback_from_text(response)
    
    def _clean_json_string(self, json_str: str) -> str:
        """Clean JSON string to fix common issues."""
        import re
        
        # Remove newlines and tabs, replace with spaces
        json_str = re.sub(r'[\n\r\t]', ' ', json_str)
        
        # Collapse multiple spaces
        json_str = re.sub(r'\s+', ' ', json_str)
        
        # Fix common trailing comma issues
        json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas before }
        json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas before ]
        
        # Fix unescaped quotes in strings (basic attempt)
        # This is a simplified approach - more sophisticated escaping might be needed
        json_str = re.sub(r'(?<!\\)"(?=[^,}\]]*[,}\]])', '\\"', json_str)
        
        return json_str.strip()
    
    def _create_fallback_from_text(self, response: str) -> Dict[str, Any]:
        """Create a basic structure from text when JSON parsing fails."""
        import re
        # Extract basic info using regex patterns
        title_match = re.search(r'"title":\s*"([^"]*)"', response)
        description_match = re.search(r'"description":\s*"([^"]*)"', response)
        
        return {
            "title": title_match.group(1) if title_match else "Unknown Form",
            "description": description_match.group(1) if description_match else "",
            "purpose": "Analysis partially failed",
            "sections": [],  # Will be empty but at least we have basic info
            "general_instructions": [],
            "warnings": ["JSON parsing failed, basic analysis only"],
            "legal_notes": []
        }
    
    def _create_form_structure(self, structure_data: Dict[str, Any], file_path: str) -> FormStructure:
        """Create FormStructure object from parsed data."""
        
        # Create sections
        sections = []
        all_fields = {}
        
        for section_data in structure_data.get("sections", []):
            # Create fields for this section
            fields = []
            for field_data in section_data.get("fields", []):
                field = FormField(
                    id=field_data.get("id", ""),
                    name=field_data.get("name", ""),
                    description=field_data.get("description"),
                    field_type=field_data.get("type", "text"),
                    required=field_data.get("required", False),
                    section_id=section_data.get("id", ""),
                    dependencies=field_data.get("dependencies", []),
                    validation_rules=field_data.get("validation_rules", []),
                    default_value=field_data.get("default_value"),
                    options=field_data.get("options"),
                    position={},  # Will be populated later if needed
                    context=field_data.get("context", "")
                )
                fields.append(field)  # Keep as FormField object
                all_fields[field.id] = field
            
            # Create section
            section = FormSection(
                id=section_data.get("id", ""),
                title=section_data.get("title", ""),
                description=section_data.get("description"),
                instructions=section_data.get("instructions", []),
                fields=fields,
                subsections=[],  # Can be expanded later
                page_number=1,  # Default, can be determined from layout analysis
                position={}
            )
            sections.append(section)
        
        # Create field relationships
        field_relationships = {}
        for field_id, field in all_fields.items():
            if field.dependencies:
                field_relationships[field_id] = field.dependencies
        
        # Create complete form structure
        form_structure = FormStructure(
            title=structure_data.get("title", "Unknown Form"),
            description=structure_data.get("description", ""),
            purpose=structure_data.get("purpose", ""),
            sections=sections,
            all_fields=all_fields,
            field_relationships=field_relationships,
            instructions=structure_data.get("general_instructions", []),
            warnings=structure_data.get("warnings", []),
            legal_notes=structure_data.get("legal_notes", []),
            total_pages=1,  # Will be updated from metadata
            language=structure_data.get("language", "de"),
            form_version=structure_data.get("form_version"),
            issuing_authority=structure_data.get("issuing_authority")
        )
        
        return form_structure
    
    def _enhance_with_pdf_fields(self, form_structure: FormStructure, pdf_fields: Dict[str, Dict[str, Any]]) -> FormStructure:
        """Enhance the form structure to ensure all real PDF fields are included."""
        
        if not pdf_fields:
            return form_structure
        
        # Get all field IDs currently in the structure
        existing_field_ids = set(form_structure.all_fields.keys())
        pdf_field_names = set(pdf_fields.keys())
        
        # Find PDF fields that aren't in the LLM analysis
        missing_pdf_fields = pdf_field_names - existing_field_ids
        
        if missing_pdf_fields:
            print(f"📝 Adding {len(missing_pdf_fields)} missing PDF fields to structure")
            
            # Find or create a "Miscellaneous" section for unmapped fields
            misc_section = None
            for section in form_structure.sections:
                if section.id.lower() in ['misc', 'other', 'additional', 'z']:
                    misc_section = section
                    break
            
            if not misc_section:
                misc_section = FormSection(
                    id="MISC",
                    title="Additional Fields",
                    description="Fields found in PDF but not categorized",
                    instructions=[],
                    fields=[],
                    subsections=[],
                    page_number=1,
                    position={}
                )
                form_structure.sections.append(misc_section)
            
            # Add missing PDF fields
            for field_name in missing_pdf_fields:
                field_info = pdf_fields[field_name]
                
                # Create field based on PDF field information
                field = FormField(
                    id=field_name,
                    name=field_name.replace('_', ' ').replace('txtf', 'Field').title(),
                    description=f"PDF form field on page {field_info['page_number']}",
                    field_type=field_info['field_type'],
                    required=field_info.get('is_required', False),
                    section_id=misc_section.id,
                    dependencies=[],
                    validation_rules=[],
                    default_value=field_info.get('current_value'),
                    options=None,
                    position=field_info.get('position', {}),
                    context=f"PDF field {field_name}"
                )
                
                misc_section.fields.append(field)
                form_structure.all_fields[field_name] = field
        
        print(f"✅ Form structure enhanced: {len(form_structure.all_fields)} total fields ({len(pdf_fields)} PDF fields)")
        return form_structure
    
    def _create_pdf_only_structure(self, raw_content: Dict[str, Any], pdf_fields: Dict[str, Dict[str, Any]], file_path: str) -> FormStructure:
        """Create form structure using only PDF field information (bypassing LLM)."""
        
        print("📋 Creating structure from PDF fields only...")
        
        # Create fields from PDF field data
        all_fields = {}
        fields_list = []
        
        for field_name, field_info in pdf_fields.items():
            field = FormField(
                id=field_name,
                name=field_name.replace('_', ' ').replace('txtf', 'Field').replace('rbtn', 'Radio').replace('chbx', 'Checkbox').title(),
                description=f"PDF form field on page {field_info['page_number']}",
                field_type=field_info['field_type'] or 'text',
                required=field_info.get('is_required', False),
                section_id="PDF_FIELDS",
                dependencies=[],
                validation_rules=[],
                default_value=field_info.get('current_value'),
                options=None,
                position=field_info.get('position', {}),
                context=f"PDF field {field_name}"
            )
            all_fields[field_name] = field
            fields_list.append(field)
        
        # Create a single section containing all PDF fields
        section = FormSection(
            id="PDF_FIELDS",
            title="Form Fields",
            description="All fields extracted from PDF form",
            instructions=[],
            fields=fields_list,
            subsections=[],
            page_number=1,
            position={}
        )
        
        # Create form structure
        form_structure = FormStructure(
            title="PDF Form",
            description="Form structure extracted from PDF fields",
            purpose="PDF form filling",
            sections=[section],
            all_fields=all_fields,
            field_relationships={},
            instructions=["Fill all required fields"],
            warnings=["LLM analysis not available - using PDF structure only"],
            legal_notes=[],
            total_pages=raw_content.get("metadata", {}).get("total_pages", 1),
            language="de",
            form_version=None,
            issuing_authority="Unknown"
        )
        
        print(f"✅ PDF-only structure created: 1 section, {len(all_fields)} fields")
        return form_structure
    
    def _create_fallback_structure(self, raw_content: Dict[str, Any], file_path: str) -> FormStructure:
        """Create a basic fallback structure if LLM analysis fails."""
        
        return FormStructure(
            title="Form Analysis Failed",
            description="Could not analyze form structure",
            purpose="Unknown",
            sections=[],
            all_fields={},
            field_relationships={},
            instructions=[],
            warnings=["Form analysis incomplete"],
            legal_notes=[],
            total_pages=raw_content.get("metadata", {}).get("total_pages", 1),
            language="unknown",
            form_version=None,
            issuing_authority=None
        )
    
    def save_analysis_result(self, form_structure: FormStructure, output_path: str) -> str:
        """Save the comprehensive form analysis to a JSON file."""
        
        # Convert dataclasses to dict for JSON serialization
        analysis_data = {
            "title": form_structure.title,
            "description": form_structure.description,
            "purpose": form_structure.purpose,
            "total_pages": form_structure.total_pages,
            "language": form_structure.language,
            "form_version": form_structure.form_version,
            "issuing_authority": form_structure.issuing_authority,
            "sections": [asdict(section) for section in form_structure.sections],
            "all_fields": {k: asdict(v) for k, v in form_structure.all_fields.items()},
            "field_relationships": form_structure.field_relationships,
            "instructions": form_structure.instructions,
            "warnings": form_structure.warnings,
            "legal_notes": form_structure.legal_notes,
            "analysis_metadata": {
                "tool_version": "1.0.0",
                "analysis_type": "comprehensive_structure",
                "timestamp": None  # Will be set by caller
            }
        }
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Comprehensive form analysis saved: {output_path}")
        return output_path