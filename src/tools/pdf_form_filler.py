"""PDF Form Filling Tool for filling PDF forms with extracted data."""
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import fitz  # PyMuPDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black
from reportlab.lib.units import inch

class PDFFormFillerTool:
    """
    Tool for filling PDF forms with extracted data.
    
    Supports:
    - Text fields
    - Checkboxes
    - Radio buttons
    - Dropdown fields
    - Signature areas (placeholder text)
    """
    
    def __init__(self):
        """Initialize the PDF form filler tool."""
        self.supported_field_types = [
            "text", "number", "date", "email", "phone", 
            "checkbox", "radio", "dropdown", "signature"
        ]
    
    def fill_pdf_form(
        self,
        template_path: str,
        data_mapping: Dict[str, Any],
        output_path: str,
        field_types: Optional[Dict[str, str]] = None,
        user_instructions: Optional[str] = None,
        form_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Fill a PDF form with the provided data mapping.
        
        Args:
            template_path: Path to the PDF form template
            data_mapping: Dictionary mapping form field names to values
            output_path: Path where the filled PDF should be saved
            field_types: Optional mapping of field names to types
            
        Returns:
            Dictionary with results and metadata
        """
        
        try:
            # Store context for LLM matching
            self._current_user_instructions = user_instructions
            self._current_form_context = form_context or {}
            
            # First, try to fill using PyMuPDF (handles interactive PDF forms)
            result = self._fill_with_pymupdf(template_path, data_mapping, output_path, field_types)
            
            if result["success"]:
                return result
            else:
                # Fallback: Create overlay approach
                print("🔄 Falling back to overlay method...")
                return self._fill_with_overlay(template_path, data_mapping, output_path, field_types)
                
        except Exception as e:
            return {
                "success": False,
                "output_path": "",
                "filled_fields": {},
                "errors": [f"PDF form filling failed: {str(e)}"],
                "method": "error"
            }
        finally:
            # Clean up context
            self._current_user_instructions = None
            self._current_form_context = {}
    
    def _fill_with_pymupdf(
        self,
        template_path: str,
        data_mapping: Dict[str, Any],
        output_path: str,
        field_types: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Fill PDF form using PyMuPDF (works with interactive PDF forms)."""
        
        try:
            print(f"📝 Filling PDF form with PyMuPDF: {template_path}")
            
            # Open the PDF document
            doc = fitz.open(template_path)
            filled_fields = {}
            errors = []
            
            # Iterate through pages to find and fill form fields
            for page_num in range(doc.page_count):
                page = doc[page_num]
                
                # Get form fields on this page
                widgets = list(page.widgets())
                
                if not widgets:
                    continue
                    
                print(f"📋 Found {len(widgets)} form fields on page {page_num + 1}")
                
                # Create a copy of widgets list to avoid iteration issues
                widgets_to_process = []
                for widget in widgets:
                    if widget.field_name:  # Only process widgets with names
                        widgets_to_process.append((widget.field_name, widget.field_type, widget))
                
                for field_name, field_type, widget in widgets_to_process:
                    # Try to find matching data for this field
                    field_value = self._find_matching_value(field_name, data_mapping, field_types)
                    
                    if field_value is not None:
                        try:
                            # Fill the field based on its type
                            success = self._fill_field_pymupdf(widget, field_value, field_type)
                            
                            if success:
                                filled_fields[field_name] = field_value
                                print(f"✅ Filled '{field_name}' with '{field_value}'")
                                    
                            else:
                                errors.append(f"Failed to fill field '{field_name}'")
                                print(f"❌ Failed to fill '{field_name}'")
                                
                        except Exception as field_error:
                            error_msg = f"Error filling field '{field_name}': {str(field_error)}"
                            errors.append(error_msg)
                            print(f"⚠️ {error_msg}")
                            # Continue to next field instead of breaking
                            continue
            
            # Calculate total fields before closing document
            total_fields_found = sum(len(list(doc[page_num].widgets())) for page_num in range(doc.page_count))
            
            # Save the filled PDF
            doc.save(output_path)
            doc.close()
            
            return {
                "success": True,
                "output_path": output_path,
                "filled_fields": filled_fields,
                "errors": errors,
                "method": "pymupdf",
                "total_fields_found": total_fields_found,
                "fields_filled": len(filled_fields)
            }
            
        except Exception as e:
            return {
                "success": False,
                "output_path": "",
                "filled_fields": {},
                "errors": [f"PyMuPDF filling failed: {str(e)}"],
                "method": "pymupdf_error"
            }
    
    def _fill_field_pymupdf(self, widget, value: str, field_type: int) -> bool:
        """Fill a specific field using PyMuPDF widget."""
        try:
            # Convert value to string and clean it
            str_value = str(value).strip()
            
            # Handle different field types
            if field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                # Text field
                widget.field_value = str_value
                widget.update()
                return True
                
            elif field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                # Checkbox - check if value indicates "checked"
                check_values = ["yes", "true", "1", "checked", "on", "x"]
                should_check = str_value.lower() in check_values
                widget.field_value = should_check
                widget.update()
                return True
                
            elif field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                # Radio button
                widget.field_value = str_value
                widget.update()
                return True
                
            elif field_type == fitz.PDF_WIDGET_TYPE_COMBOBOX:
                # Dropdown/Combobox
                widget.field_value = str_value
                widget.update()
                return True
                
            else:
                # Try as text field for unknown types
                widget.field_value = str_value
                widget.update()
                return True
                
        except Exception as e:
            print(f"⚠️ Error filling widget: {str(e)}")
            return False
    
    def _fill_with_overlay(
        self,
        template_path: str,
        data_mapping: Dict[str, Any],
        output_path: str,
        field_types: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Fill PDF by overlaying text (fallback method for non-interactive PDFs)."""
        
        try:
            print(f"📝 Creating overlay for PDF: {template_path}")
            
            # This is a simplified overlay approach
            # In a production system, you'd want more sophisticated field positioning
            
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            import tempfile
            
            # Create a temporary overlay PDF
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                overlay_path = temp_file.name
            
            # Create overlay with form data
            c = canvas.Canvas(overlay_path, pagesize=letter)
            width, height = letter
            
            filled_fields = {}
            y_position = height - 100  # Start from top
            
            # Simple text overlay (this would need field positioning in real implementation)
            c.setFont("Helvetica", 10)
            
            for field_name, value in data_mapping.items():
                if value and str(value).strip():
                    display_text = f"{field_name}: {value}"
                    c.drawString(50, y_position, display_text)
                    filled_fields[field_name] = value
                    y_position -= 20
                    
                    if y_position < 50:  # Start new page if needed
                        c.showPage()
                        y_position = height - 100
                        c.setFont("Helvetica", 10)
            
            c.save()
            
            # Merge overlay with original PDF
            try:
                import fitz
                
                # Open both PDFs
                original_doc = fitz.open(template_path)
                overlay_doc = fitz.open(overlay_path)
                
                # Overlay the content
                for page_num in range(min(original_doc.page_count, overlay_doc.page_count)):
                    original_page = original_doc[page_num]
                    overlay_page = overlay_doc[page_num]
                    
                    # Insert overlay content
                    original_page.show_pdf_page(
                        original_page.rect, overlay_doc, page_num
                    )
                
                # Save result
                original_doc.save(output_path)
                original_doc.close()
                overlay_doc.close()
                
                # Clean up
                os.unlink(overlay_path)
                
                return {
                    "success": True,
                    "output_path": output_path,
                    "filled_fields": filled_fields,
                    "errors": [],
                    "method": "overlay",
                    "total_fields_found": len(data_mapping),
                    "fields_filled": len(filled_fields)
                }
                
            except Exception as merge_error:
                # If merge fails, just copy the template and create a summary
                import shutil
                shutil.copy2(template_path, output_path)
                
                return {
                    "success": True,
                    "output_path": output_path,
                    "filled_fields": filled_fields,
                    "errors": [f"Could not overlay data: {str(merge_error)}"],
                    "method": "template_copy",
                    "total_fields_found": len(data_mapping),
                    "fields_filled": 0
                }
                
        except Exception as e:
            return {
                "success": False,
                "output_path": "",
                "filled_fields": {},
                "errors": [f"Overlay filling failed: {str(e)}"],
                "method": "overlay_error"
            }
    
    def _find_matching_value(
        self,
        field_name: str,
        data_mapping: Dict[str, Any],
        field_types: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """Find the best matching value for a form field using intelligent matching."""
        
        # Direct match (fastest path)
        if field_name in data_mapping:
            value = data_mapping[field_name]
            return self._format_value_for_field(value, field_name, field_types)
        
        # Case-insensitive match
        field_name_lower = field_name.lower()
        for key, value in data_mapping.items():
            if key.lower() == field_name_lower:
                return self._format_value_for_field(value, field_name, field_types)
        
        # Enhanced semantic matching
        best_match = self._find_semantic_match(field_name, data_mapping)
        if best_match:
            return self._format_value_for_field(best_match, field_name, field_types)
        
        return None

    def _find_semantic_match(self, field_name: str, data_mapping: Dict[str, Any]) -> Optional[str]:
        """Use intelligent semantic matching to find the best field match."""
        
        # Try LLM-based matching first (more accurate)
        try:
            llm_result = self._find_llm_based_match(field_name, data_mapping)
            if llm_result:
                return llm_result
        except Exception as e:
            print(f"⚠️ LLM matching failed for '{field_name}': {e}")
        
        # Fallback to similarity matching
        return self._find_simple_similarity_match(field_name, data_mapping)

    def _find_simple_similarity_match(self, field_name: str, data_mapping: Dict[str, Any]) -> Optional[str]:
        """Find match using simple similarity rules."""
        field_name_lower = field_name.lower()
        
        for key, value in data_mapping.items():
            if (key.lower() in field_name_lower or 
                field_name_lower in key.lower() or
                self._is_similar_field(field_name_lower, key.lower())):
                return value
        
        return None

    def _find_llm_based_match(self, field_name: str, data_mapping: Dict[str, Any]) -> Optional[str]:
        """Use LLM to find semantic matches between form fields and extracted data."""
        
        # Import here to avoid circular imports
        try:
            from src.llm_client import get_llm_client
            llm_client = get_llm_client()
        except Exception:
            # If LLM client not available, fallback
            return None
        
        # Create a context-aware prompt for field matching
        user_context = getattr(self, '_current_user_instructions', None)
        form_context = getattr(self, '_current_form_context', {})
        
        system_prompt = f"""You are a field matching specialist. Your task is to find the best semantic match between a form field name and available data fields.

CORE RULES:
1. Match fields based on semantic meaning, not just spelling
2. Handle different languages (German ↔ English)
3. Consider medical/business terminology variations
4. Return ONLY the matching data field name or "NO_MATCH"

USER REQUIREMENTS:
{user_context or "Standard semantic matching - prioritize accuracy and relevance"}

FORM CONTEXT:
{f"Form type: {form_context.get('form_type', 'Generic')}" if form_context else "Generic form"}
{f"Domain: {form_context.get('domain', 'General')}" if form_context else ""}

MATCHING EXAMPLES:
- Form field "patient_id" matches data field "Patienten Id" or "Patient Number"
- Form field "diagnose" matches data field "Zusammenfassung" or "Diagnosis" 
- Form field "datum" matches data field "Date" or "Mdt Datum"

INSTRUCTIONS: Consider the user requirements above when making semantic matches. Prioritize matches that align with the specified preferences and business rules.

Response format: Just the matching data field name or "NO_MATCH"."""

        data_keys = list(data_mapping.keys())
        user_message = f"""Form field to match: "{field_name}"

Available data fields:
{chr(10).join(f"- {key}" for key in data_keys)}

Which data field best matches "{field_name}" semantically?"""

        try:
            messages = llm_client.create_messages(system_prompt, user_message)
            response = llm_client.invoke_sync(messages)
            
            suggested_match = response.content.strip()
            
            # Validate the suggestion
            if suggested_match == "NO_MATCH":
                return None
                
            # Find the suggested field in our data (case-insensitive)
            for key, value in data_mapping.items():
                if key.lower() == suggested_match.lower() or suggested_match.lower() in key.lower():
                    print(f"🧠 LLM matched '{field_name}' → '{key}'")
                    return value
            
            return None
            
        except Exception as e:
            print(f"⚠️ LLM field matching error: {e}")
            return None
    
    def _is_similar_field(self, field1: str, field2: str) -> bool:
        """Check if two field names are similar using generic pattern matching."""
        # Remove common separators and compare
        clean1 = field1.replace('_', '').replace('-', '').replace(' ', '').lower()
        clean2 = field2.replace('_', '').replace('-', '').replace(' ', '').lower()
        
        # Direct match after cleaning
        if clean1 == clean2:
            return True
        
        # Check for substring matches (both directions)
        if len(clean1) > 2 and len(clean2) > 2:
            # One is contained in the other
            if clean1 in clean2 or clean2 in clean1:
                return True
            
            # Check for common roots (at least 60% similarity for longer strings)
            if len(clean1) >= 5 and len(clean2) >= 5:
                shorter = min(clean1, clean2, key=len)
                longer = max(clean1, clean2, key=len)
                
                # Check if shorter string matches beginning or end of longer string
                if (longer.startswith(shorter[:len(shorter)//2]) or 
                    longer.endswith(shorter[len(shorter)//2:]) or
                    shorter.startswith(longer[:len(longer)//2]) or
                    shorter.endswith(longer[len(longer)//2:])):
                    return True
        
        # Check for very similar character patterns (edit distance)
        if len(clean1) > 3 and len(clean2) > 3:
            # Simple character overlap check
            common_chars = set(clean1) & set(clean2)
            min_len = min(len(clean1), len(clean2))
            if len(common_chars) >= min_len * 0.7:  # 70% character overlap
                return True
        
        return False
    
    def _format_value_for_field(
        self,
        value: Any,
        field_name: str,
        field_types: Optional[Dict[str, str]] = None
    ) -> str:
        """Format a value appropriately for a form field."""
        
        if value is None:
            return ""
        
        str_value = str(value).strip()
        
        # Get field type
        field_type = None
        if field_types and field_name in field_types:
            field_type = field_types[field_name].lower()
        else:
            # Infer type from field name
            field_name_lower = field_name.lower()
            if 'date' in field_name_lower or 'birth' in field_name_lower:
                field_type = 'date'
            elif 'phone' in field_name_lower or 'tel' in field_name_lower:
                field_type = 'phone'
            elif 'email' in field_name_lower or 'mail' in field_name_lower:
                field_type = 'email'
            elif 'checkbox' in field_name_lower or 'check' in field_name_lower:
                field_type = 'checkbox'
        
        # Format based on type
        if field_type == 'date':
            return self._format_date(str_value)
        elif field_type == 'phone':
            return self._format_phone(str_value)
        elif field_type == 'email':
            return self._format_email(str_value)
        elif field_type == 'checkbox':
            return self._format_checkbox(str_value)
        else:
            return str_value
    
    def _format_date(self, value: str) -> str:
        """Format date values."""
        # Try to parse and reformat common date patterns
        import re
        
        # Remove extra whitespace
        value = re.sub(r'\s+', ' ', value.strip())
        
        # Common date patterns
        date_patterns = [
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',  # MM/DD/YYYY or MM-DD-YYYY
            r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',  # YYYY/MM/DD or YYYY-MM-DD
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',  # DD Month YYYY
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, value, re.IGNORECASE)
            if match:
                return value  # Return as-is if it matches a date pattern
        
        return value
    
    def _format_phone(self, value: str) -> str:
        """Format phone number values."""
        import re
        
        # Extract digits only
        digits = re.sub(r'[^\d]', '', value)
        
        # Format US phone numbers
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == '1':
            return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            return value  # Return original if not standard format
    
    def _format_email(self, value: str) -> str:
        """Format email values."""
        return value.lower().strip()
    
    def _format_checkbox(self, value: str) -> str:
        """Format checkbox values."""
        check_values = ["yes", "true", "1", "checked", "on", "x", "✓"]
        return "✓" if value.lower() in check_values else ""
    
    def analyze_form_fields(self, pdf_path: str) -> Dict[str, Any]:
        """Analyze a PDF form to identify available fields."""
        
        try:
            doc = fitz.open(pdf_path)
            fields_info = {}
            
            for page_num in range(doc.page_count):
                page = doc[page_num]
                widgets = list(page.widgets())
                
                for widget in widgets:
                    if widget.field_name:
                        field_info = {
                            "page": page_num + 1,
                            "type": self._get_field_type_name(widget.field_type),
                            "rect": list(widget.rect),
                            "value": widget.field_value,
                            "choices": getattr(widget, 'choice_values', []),
                        }
                        fields_info[widget.field_name] = field_info
            
            doc.close()
            
            return {
                "success": True,
                "fields": fields_info,
                "total_fields": len(fields_info),
                "pages": doc.page_count
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "fields": {},
                "total_fields": 0,
                "pages": 0
            }
    
    def _get_field_type_name(self, field_type: int) -> str:
        """Convert PyMuPDF field type to readable name."""
        type_mapping = {
            fitz.PDF_WIDGET_TYPE_TEXT: "text",
            fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
            fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
            fitz.PDF_WIDGET_TYPE_COMBOBOX: "dropdown",
            fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox",
            fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
        }
        return type_mapping.get(field_type, "unknown")
