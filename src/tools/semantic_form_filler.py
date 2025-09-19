"""
Semantic Form Filler Tool - Advanced form filling using semantic extraction and form learning insights.

This tool combines:
1. Form structure analysis (from form_learner)
2. Semantic extraction results (from data_extractor) 
3. Intelligent field mapping and form filling

It eliminates redundant LLM processing by leveraging the rich context already gathered.
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
import fitz  # PyMuPDF

from src.models import AgentState, FormFillingResult
from src.llm_client import get_llm_client


@dataclass
class SemanticFieldMapping:
    """Represents a semantic mapping between extracted data and form field."""
    form_field_name: str
    form_field_id: str  
    form_field_type: str
    extracted_value: Any
    confidence: float
    extraction_field_id: str  # Original field ID from semantic extraction (e.g., "B3")
    extraction_field_name: str  # Original field name from semantic extraction
    mapping_method: str  # How this mapping was determined


@dataclass
class SemanticFormFillingResult:
    """Enhanced result with semantic mapping information."""
    output_file_path: str
    semantic_mappings: List[SemanticFieldMapping]
    success: bool
    errors: Optional[List[str]] = None
    total_form_fields: int = 0
    fields_attempted: int = 0
    fields_filled: int = 0
    unmapped_extracted_fields: List[str] = None
    unfilled_form_fields: List[str] = None


class SemanticFormFillerTool:
    """
    Advanced form filler that uses semantic extraction and form learning insights.
    
    This tool:
    1. Takes semantic extraction results (field names + values + confidence)
    2. Uses form structure analysis (field positions, types, contexts)
    3. Creates intelligent mappings without redundant LLM processing
    4. Fills forms with high accuracy using comprehensive context
    """

    def __init__(self):
        """Initialize the semantic form filler."""
        self.supported_formats = ['.pdf', '.xlsx', '.xlsm']
        self.llm_client = get_llm_client()

    async def fill_form_semantically(
        self,
        state: AgentState,
        output_path: str
    ) -> SemanticFormFillingResult:
        """
        Fill form using semantic extraction results and form learning insights.
        
        Args:
            state: AgentState with form_structure, extracted_data, and other context
            output_path: Where to save the filled form
            
        Returns:
            SemanticFormFillingResult with detailed mapping information
        """
        
        try:
            print("🧠 Starting semantic form filling...")
            
            # Step 1: Create semantic mappings using form learning insights
            semantic_mappings = self._create_semantic_mappings(state)
            
            print(f"📊 Created {len(semantic_mappings)} semantic mappings")
            
            # Step 2: Determine form type and fill accordingly
            file_extension = os.path.splitext(state.form_template_path)[1].lower()
            
            if file_extension == '.pdf':
                result = await self._fill_pdf_semantically(
                    state.form_template_path, 
                    semantic_mappings, 
                    output_path,
                    state
                )
            elif file_extension in ['.xlsx', '.xlsm']:
                # Use the dedicated semantic Excel form filler
                from .semantic_excel_form_filler import SemanticExcelFormFillerTool
                
                excel_filler = SemanticExcelFormFillerTool()
                excel_result = await excel_filler.fill_excel_form_semantically(state, output_path)
                
                # Convert Excel result to standard SemanticFormFillingResult
                result = SemanticFormFillingResult(
                    output_file_path=excel_result.output_file_path,
                    semantic_mappings=[
                        SemanticFieldMapping(
                            form_field_name=mapping.form_field_name,
                            form_field_id=mapping.form_field_id,
                            form_field_type=mapping.form_field_type,
                            extracted_value=mapping.extracted_value,
                            confidence=mapping.confidence,
                            extraction_field_id=mapping.extraction_field_id,
                            extraction_field_name=mapping.extraction_field_name,
                            mapping_method=mapping.mapping_method
                        )
                        for mapping in excel_result.semantic_mappings
                    ],
                    success=excel_result.success,
                    errors=excel_result.errors,
                    total_form_fields=excel_result.total_form_fields,
                    fields_attempted=excel_result.fields_attempted,
                    fields_filled=excel_result.fields_filled,
                    unmapped_extracted_fields=excel_result.unmapped_extracted_fields,
                    unfilled_form_fields=excel_result.unfilled_form_fields
                )
            else:
                # Fallback to text-based form
                result = self._create_text_form(semantic_mappings, output_path, state)
            
            # Step 3: Save semantic mapping details
            await self._save_semantic_mapping_report(semantic_mappings, state, output_path)
            
            return result
            
        except Exception as e:
            print(f"❌ Semantic form filling error: {str(e)}")
            return SemanticFormFillingResult(
                output_file_path="",
                semantic_mappings=[],
                success=False,
                errors=[f"Semantic form filling failed: {str(e)}"]
            )

    def _create_semantic_mappings(self, state: AgentState) -> List[SemanticFieldMapping]:
        """
        Create semantic mappings using form structure and extraction results.
        
        This is the key improvement - we use the rich context from form learning
        to create precise mappings without additional LLM calls.
        """
        mappings = []
        
        # Get form structure from form learning
        form_structure = getattr(state, 'form_structure', None)
        if not form_structure:
            print("⚠️ No form structure available - using basic mapping")
            return self._create_basic_mappings(state)
        
        # Get extracted data (field_id -> value mapping from semantic extraction)
        extracted_data = state.extracted_data or {}
        
        print(f"🔍 Processing {len(extracted_data)} extracted fields against form structure")
        
        # Process each section in the form structure
        for section in form_structure.get('sections', []):
            section_title = section.get('title', '')
            print(f"📋 Processing section: {section_title}")
            
            for field in section.get('fields', []):
                field_id = field.get('id')
                field_name = field.get('name') 
                field_type = field.get('field_type') or 'text'  # Default to 'text' if None
                
                if not field_id or not field_name:
                    continue
                
                # Look for extracted data with this field_id
                if field_id in extracted_data:
                    extracted_value = extracted_data[field_id]
                    
                    # Create semantic mapping
                    mapping = SemanticFieldMapping(
                        form_field_name=field_name,
                        form_field_id=field_id,
                        form_field_type=field_type,
                        extracted_value=extracted_value,
                        confidence=0.95,  # High confidence since we have direct ID match
                        extraction_field_id=field_id,
                        extraction_field_name=field_name,
                        mapping_method="direct_semantic_match"
                    )
                    
                    mappings.append(mapping)
                    print(f"✅ Mapped {field_id} ({field_name}): {extracted_value}")
                
                else:
                    # Try to find semantic match in extracted data
                    semantic_match = self._find_semantic_match_in_extraction(
                        field_name, field_type, extracted_data
                    )
                    
                    if semantic_match:
                        ext_field_id, ext_value, confidence = semantic_match
                        
                        mapping = SemanticFieldMapping(
                            form_field_name=field_name,
                            form_field_id=field_id,
                            form_field_type=field_type,
                            extracted_value=ext_value,
                            confidence=confidence,
                            extraction_field_id=ext_field_id,
                            extraction_field_name=field_name,
                            mapping_method="semantic_match"
                        )
                        
                        mappings.append(mapping)
                        print(f"🔍 Semantic match {field_id} ({field_name}): {ext_value} (confidence: {confidence:.1%})")
        
        print(f"✅ Created {len(mappings)} semantic mappings")
        # Debug: Show all mapping field names
        mapping_names = [f"{m.form_field_id}→{m.form_field_name}" for m in mappings]
        print(f"📝 Mapping details: {mapping_names[:10]}")  # Show first 10
        return mappings

    def _find_semantic_match_in_extraction(
        self, 
        field_name: str, 
        field_type: str, 
        extracted_data: Dict[str, Any]
    ) -> Optional[Tuple[str, Any, float]]:
        """
        Find semantic matches using field name similarity and type compatibility.
        
        Returns: (extracted_field_id, value, confidence) or None
        """
        
        field_name_lower = field_name.lower()
        best_match = None
        best_confidence = 0.0
        
        # Define semantic relationships
        name_similarities = {
            'vorname': ['first', 'name', 'prénom'],
            'nachname': ['last', 'surname', 'family', 'nom'],  
            'geburtsdatum': ['birth', 'born', 'date', 'naissance'],
            'staatsangehörigkeit': ['nationality', 'citizen', 'nationalité'],
            'telefon': ['phone', 'tel', 'téléphone'],
            'email': ['mail', 'e-mail', 'courriel'],
            'adresse': ['address', 'street', 'strasse'],
            'firma': ['company', 'employer', 'entreprise'],
        }
        
        for ext_field_id, value in extracted_data.items():
            confidence = 0.0
            
            # Direct name match
            if field_name_lower in ext_field_id.lower() or ext_field_id.lower() in field_name_lower:
                confidence = 0.85
            
            # Semantic similarity check
            else:
                for key_term, similar_terms in name_similarities.items():
                    if key_term in field_name_lower:
                        for term in similar_terms:
                            if term in ext_field_id.lower():
                                confidence = 0.75
                                break
            
            # Type compatibility boost
            if field_type == 'date' and isinstance(value, str):
                if any(char.isdigit() for char in value) and ('.' in value or '-' in value or '/' in value):
                    confidence += 0.1
            elif field_type == 'email' and isinstance(value, str):
                if '@' in value:
                    confidence += 0.15
            elif field_type == 'text' and isinstance(value, str):
                confidence += 0.05
            
            # Update best match if this is better
            if confidence > best_confidence and confidence > 0.5:
                best_match = (ext_field_id, value, confidence)
                best_confidence = confidence
        
        return best_match

    def _create_basic_mappings(self, state: AgentState) -> List[SemanticFieldMapping]:
        """Fallback mapping when form structure is not available."""
        mappings = []
        extracted_data = state.extracted_data or {}
        
        for field_id, value in extracted_data.items():
            mapping = SemanticFieldMapping(
                form_field_name=field_id,  # Use field_id as name
                form_field_id=field_id,
                form_field_type="text",  # Default type
                extracted_value=value,
                confidence=0.7,  # Lower confidence for basic mapping
                extraction_field_id=field_id,
                extraction_field_name=field_id,
                mapping_method="basic_mapping"
            )
            mappings.append(mapping)
        
        return mappings

    def _find_semantic_field_match(self, widget, semantic_mappings: List[SemanticFieldMapping]) -> SemanticFieldMapping:
        """Find the best semantic match between a PDF widget and semantic mappings."""
        
        # Extract meaningful parts from PDF field name
        field_name = widget.field_name.lower()
        
        # Define semantic mapping patterns (gradually reducing for LLM replacement)
        semantic_patterns = {
            # 'vorname': ['vorname', 'firstname', 'first_name', 'given_name'],  # LLM handles this well
            # 'nachname': ['nachname', 'lastname', 'last_name', 'surname', 'family_name'],  # LLM handles this well
            # 'geburtsdatum': ['geburtsdatum', 'birthdate', 'birth_date', 'dateofbirth', 'dob'],  # LLM handles this well
            'geschlecht': ['geschlecht', 'gender', 'sex'],
            # 'staatsangehoerigkeit': ['staatsangehoerigkeit', 'nationality', 'citizenship'],  # LLM handles this well
            # 'wohnsitz': ['wohnsitz', 'residence', 'address', 'adresse'],  # LLM handles this well
            # 'firma': ['firma', 'company', 'unternehmen', 'employer'],  # LLM handles this well
            # 'strasse': ['strasse', 'street', 'straße'],  # LLM handles this well
            # 'hausnummer': ['hausnummer', 'house_number', 'number'],  # LLM handles this well
            # 'postleitzahl': ['postleitzahl', 'postal_code', 'zip_code', 'plz'],  # LLM handles this well
            # 'ort': ['ort', 'city', 'town', 'place'],  # LLM handles this well
            # 'telefon': ['telefon', 'phone', 'telephone'],  # LLM handles this well
            # 'email': ['email', 'e-mail', 'mail'],  # LLM handles this well
            # 'telefax': ['telefax', 'fax'],  # LLM handles this well
            # 'betriebsnummer': ['betriebsnummer', 'company_number'],  # LLM handles this well
            # 'kontaktperson': ['kontaktperson', 'contact_person', 'contact'],  # LLM handles this well
            # 'studiengang': ['studiengang', 'course_of_study', 'study_program'],  # LLM handles this well
            # 'hochschulabschluss': ['hochschulabschluss', 'university_degree', 'degree'],  # LLM handles this well
            # 'berufsbezeichnung': ['berufsbezeichnung', 'job_title', 'profession'],  # LLM handles this well
            # 'arbeitszeit': ['arbeitszeit', 'working_time', 'work_hours'],  # LLM handles this well
            # 'entgelt': ['entgelt', 'salary', 'wage', 'pay'],  # LLM handles this well
            # 'datum': ['datum', 'date'],  # LLM handles this well
            # 'ort': ['ort', 'place', 'location']  # LLM handles this well
        }
        
        best_match = None
        best_score = 0.0
        
        for mapping in semantic_mappings:
            score = 0.0
            mapping_name = mapping.form_field_name.lower()
            
            # Check if PDF field name contains semantic keywords
            for semantic_key, patterns in semantic_patterns.items():
                if any(pattern in field_name for pattern in patterns):
                    if any(pattern in mapping_name for pattern in patterns):
                        score += 0.8
                        break
                    if semantic_key in mapping_name:
                        score += 0.6
            
            # Direct name similarity
            if mapping_name in field_name or field_name in mapping_name:
                score += 0.7
            
            # Check for German-English equivalents
            german_english_map = {
                'vorname': 'firstname',
                'nachname': 'lastname', 
                'geburtsdatum': 'birthdate',
                'geschlecht': 'gender',
                'staatsangehoerigkeit': 'nationality',
                'firma': 'company',
                'strasse': 'street',
                'ort': 'city',
                'telefon': 'phone',
                'datum': 'date'
            }
            
            for german, english in german_english_map.items():
                if german in field_name and english in mapping_name:
                    score += 0.9
                elif english in field_name and german in mapping_name:
                    score += 0.9
            
            # Boost score based on confidence
            score *= mapping.confidence
            
            if score > best_score and score > 0.5:
                best_match = mapping
                best_score = score
        
        return best_match

    def _extract_form_context_for_field(self, pdf_field_name: str, state: AgentState) -> Dict[str, Any]:
        """
        Extract relevant form structure context for a PDF field to enhance LLM matching.
        
        Args:
            pdf_field_name: The PDF field name to find context for
            state: AgentState containing form_structure from form learner
            
        Returns:
            Dictionary with contextual information about the field
        """
        context = {
            'section': None,
            'section_title': None, 
            'field_description': None,
            'field_context': None,
            'related_fields': [],
            'field_type': None,
            'form_instructions': [],
            'surrounding_context': None
        }
        
        # Get form structure from state
        form_structure = getattr(state, 'form_structure', None)
        if not form_structure:
            return context
            
        # Search through sections and fields for matches or related context
        for section in form_structure.get('sections', []):
            section_id = section.get('id', '')
            section_title = section.get('title', '')
            
            for field in section.get('fields', []):
                field_id = field.get('id', '')
                field_name = field.get('name', '')
                
                # Prioritize exact field ID match first
                if field_id and field_id.lower() == pdf_field_name.lower():
                    context.update({
                        'section': section_id,
                        'section_title': section_title,
                        'field_description': field.get('description'),
                        'field_context': field.get('context'),
                        'field_type': field.get('type'),
                        'surrounding_context': f"Field in section '{section_title}': {field.get('description', '')}"
                    })
                    
                    # Find related fields in the same section
                    context['related_fields'] = [
                        f.get('name', f.get('id', '')) for f in section.get('fields', [])
                        if f.get('id') != field_id and f.get('name')
                    ][:3]  # Limit to 3 related fields
                    
                    return context  # Return immediately on exact match
                
                # If no exact match, try partial matches (but less reliable)
                elif not context.get('section'):  # Only if we haven't found a match yet
                    if (field_id and field_id.lower() in pdf_field_name.lower()) or \
                       (pdf_field_name.lower() in field_id.lower()) or \
                       (field_name and any(word in pdf_field_name.lower() for word in field_name.lower().split())):
                        
                        context.update({
                            'section': section_id,
                            'section_title': section_title,
                            'field_description': field.get('description'),
                            'field_context': field.get('context'),
                            'field_type': field.get('type'),
                            'surrounding_context': f"Field in section '{section_title}': {field.get('description', '')}"
                        })
                        
                        # Find related fields in the same section
                        context['related_fields'] = [
                            f.get('name', f.get('id', '')) for f in section.get('fields', [])
                            if f.get('id') != field_id and f.get('name')
                        ][:3]  # Limit to 3 related fields
        
        # Add general form instructions
        context['form_instructions'] = form_structure.get('instructions', [])[:2]  # Limit to 2 instructions
        
        return context

    async def _find_semantic_field_match_llm(self, widget, semantic_mappings: List[SemanticFieldMapping], state: AgentState) -> Optional[SemanticFieldMapping]:
        """Find the best semantic match using LLM-based field understanding with rich form context."""
        
        try:
            pdf_field_name = widget.field_name.strip()
            
            # Extract contextual information from form structure
            form_context = self._extract_form_context_for_field(pdf_field_name, state)
            
            # Debug output to verify context extraction
            if form_context['section_title'] or form_context['field_description']:
                print(f"🔍 Context for '{pdf_field_name}': {form_context['section_title']} | {form_context['field_description']}")
            
            # Create candidate list from semantic mappings
            candidates = []
            for i, mapping in enumerate(semantic_mappings):
                candidates.append({
                    'index': i,
                    'field_name': mapping.form_field_name,
                    'field_id': mapping.form_field_id,
                    'field_type': mapping.form_field_type,
                    'extracted_value': str(mapping.extracted_value)[:100],  # Limit value length
                    'confidence': mapping.confidence
                })
            
            # Debug: Show candidate field names being presented to LLM
            if candidates:
                candidate_names = [c['field_name'] for c in candidates]
                print(f"🤖 LLM candidates for '{pdf_field_name}' (total: {len(candidates)}): {candidate_names[:10]}...")  # Show first 10 for readability
                if len(candidates) > 10:
                    print(f"    📝 Plus {len(candidates) - 10} more candidates")
            
            # Build enhanced context information
            context_info = []
            if form_context['section_title']:
                context_info.append(f"📋 Section: {form_context['section_title']}")
            if form_context['field_description']:
                context_info.append(f"📝 Description: {form_context['field_description']}")
            if form_context['field_context']:
                context_info.append(f"🔍 Context: {form_context['field_context']}")
            if form_context['related_fields']:
                context_info.append(f"🔗 Related fields: {', '.join(form_context['related_fields'])}")
            if form_context['field_type']:
                context_info.append(f"🏷️ Expected type: {form_context['field_type']}")
            
            context_section = "\n".join(context_info) if context_info else "No additional context available"
            
            # Create enhanced LLM prompt with form structure context
            prompt = f"""
You are an expert at matching form field names across languages and formats, with deep understanding of form structure and context.

PDF FIELD TO MATCH: "{pdf_field_name}"

FORM CONTEXT:
{context_section}

EXTRACTED DATA CANDIDATES:
{json.dumps(candidates, indent=2)}  

TASK:
Find the best semantic match for the PDF field "{pdf_field_name}" from the extracted data candidates.

PRIORITY MATCHING RULES (in order of importance):
1. **FIELD NAME SEMANTICS** (highest priority): Match field names across languages
   - "vorname" = "firstname" = "first name" 
   - "nachname" = "lastname" = "last name"
   - "geburtsdatum" = "birthdate" = "date of birth"
   - "kontaktperson" = "contact person" = "contact"
   - Field name meaning ALWAYS takes precedence over section context

2. **FIELD TYPE COMPATIBILITY**: Data type should match expected field type
3. **SECTION CONTEXT**: Use section info only for disambiguation between equally good name matches
4. **LANGUAGE VARIATIONS**: Consider German/English equivalents

CRITICAL: If the field name clearly indicates a specific meaning (like "vorname" = first name), 
DO NOT match it to unrelated data just because of section context. Field semantics override section placement.

MATCHING CRITERIA:
- Semantic similarity must be >80% for a match
- Prioritize exact semantic field name matches over section context
- Only use section context when field names are ambiguous

Return ONLY the candidate index (0-{len(candidates)-1}) of the best match, or -1 if no good match exists.

ANSWER (just the number):
"""

            messages = self.llm_client.create_messages(
                "You are a form field matching expert specializing in semantic understanding across languages.",
                prompt
            )
            
            response = await self.llm_client.invoke(messages)
            response_text = response.content.strip()
            
            # Parse the response
            try:
                match_index = int(response_text)
                if 0 <= match_index < len(semantic_mappings):
                    matched_mapping = semantic_mappings[match_index]
                    print(f"🧠 LLM matched '{pdf_field_name}' → '{matched_mapping.form_field_name}' (confidence: {matched_mapping.confidence:.1%})")
                    return matched_mapping
                elif match_index == -1:
                    print(f"🧠 LLM found no good match for '{pdf_field_name}'")
                    return None
                else:
                    print(f"⚠️ LLM returned invalid index {match_index} for '{pdf_field_name}'")
                    return None
            except ValueError:
                print(f"⚠️ LLM returned non-numeric response for '{pdf_field_name}': {response_text}")
                return None
                
        except Exception as e:
            print(f"⚠️ LLM field matching failed for '{pdf_field_name}': {str(e)}")
            return None

    async def _fill_pdf_semantically(
        self,
        template_path: str,
        semantic_mappings: List[SemanticFieldMapping],
        output_path: str,
        state: AgentState
    ) -> SemanticFormFillingResult:
        """Fill PDF using semantic mappings."""
        
        try:
            print(f"📝 Filling PDF with {len(semantic_mappings)} semantic mappings")
            
            # Open PDF document
            doc = fitz.open(template_path)
            filled_count = 0
            attempted_count = 0
            errors = []
            unfilled_fields = []
            
            # Get all form fields in the PDF for reference
            total_fields = 0
            all_pdf_fields = []
            
            for page_num in range(doc.page_count):
                page = doc[page_num]
                widgets = list(page.widgets())
                total_fields += len(widgets)
                
                for widget in widgets:
                    if widget.field_name:
                        all_pdf_fields.append(widget.field_name)
            
            # Apply semantic mappings to PDF fields
            for page_num in range(doc.page_count):
                page = doc[page_num]
                widgets = list(page.widgets())
                
                for widget in widgets:
                    if not widget.field_name:
                        continue
                    
                    # Find matching semantic mapping using LLM first, fallback to hardcoded patterns
                    matching_mapping = await self._find_semantic_field_match_llm(widget, semantic_mappings, state)
                    
                    # Fallback to hardcoded patterns if LLM fails
                    if matching_mapping is None:
                        matching_mapping = self._find_semantic_field_match(widget, semantic_mappings)
                    
                    if matching_mapping:
                        attempted_count += 1
                        try:
                            # Format value according to field type
                            formatted_value = self._format_value_for_pdf_field(
                                matching_mapping.extracted_value,
                                matching_mapping.form_field_type,
                                widget.field_type
                            )
                            
                            # Fill the field
                            widget.field_value = str(formatted_value)
                            widget.update()
                            filled_count += 1
                            
                            print(f"✅ Filled '{widget.field_name}' with '{formatted_value}' (confidence: {matching_mapping.confidence:.1%})")
                            
                        except Exception as e:
                            error_msg = f"Failed to fill '{widget.field_name}': {str(e)}"
                            errors.append(error_msg)
                            print(f"❌ {error_msg}")
                    
                    else:
                        unfilled_fields.append(widget.field_name)
            
            # Save filled PDF
            doc.save(output_path)
            doc.close()
            
            # Identify unmapped extracted fields
            mapped_field_ids = {mapping.extraction_field_id for mapping in semantic_mappings}
            all_extracted_ids = set(state.extracted_data.keys()) if state.extracted_data else set()
            unmapped_extracted = list(all_extracted_ids - mapped_field_ids)
            
            return SemanticFormFillingResult(
                output_file_path=output_path,
                semantic_mappings=semantic_mappings,
                success=True,
                errors=errors if errors else None,
                total_form_fields=total_fields,
                fields_attempted=attempted_count,
                fields_filled=filled_count,
                unmapped_extracted_fields=unmapped_extracted,
                unfilled_form_fields=unfilled_fields
            )
            
        except Exception as e:
            return SemanticFormFillingResult(
                output_file_path="",
                semantic_mappings=semantic_mappings,
                success=False,
                errors=[f"PDF filling error: {str(e)}"]
            )

    async def _fill_excel_semantically(
        self,
        template_path: str,
        semantic_mappings: List[SemanticFieldMapping],
        output_path: str,
        state: AgentState
    ) -> SemanticFormFillingResult:
        """Fill Excel using semantic mappings - placeholder for future implementation."""
        
        # For now, create a basic Excel output with the semantic mappings
        try:
            import pandas as pd
            
            # Create a DataFrame from semantic mappings
            mapping_data = []
            for mapping in semantic_mappings:
                mapping_data.append({
                    'Field_Name': mapping.form_field_name,
                    'Field_ID': mapping.form_field_id,
                    'Field_Type': mapping.form_field_type,
                    'Value': mapping.extracted_value,
                    'Confidence': f"{mapping.confidence:.1%}",
                    'Mapping_Method': mapping.mapping_method
                })
            
            df = pd.DataFrame(mapping_data)
            df.to_excel(output_path, index=False)
            
            return SemanticFormFillingResult(
                output_file_path=output_path,
                semantic_mappings=semantic_mappings,
                success=True,
                total_form_fields=len(semantic_mappings),
                fields_filled=len(semantic_mappings)
            )
            
        except Exception as e:
            return SemanticFormFillingResult(
                output_file_path="",
                semantic_mappings=semantic_mappings,
                success=False,
                errors=[f"Excel filling error: {str(e)}"]
            )

    def _create_text_form(
        self,
        semantic_mappings: List[SemanticFieldMapping],
        output_path: str,
        state: AgentState
    ) -> SemanticFormFillingResult:
        """Create a text-based form as fallback."""
        
        try:
            content = []
            content.append("=" * 60)
            content.append("SEMANTIC FORM FILLING RESULT")
            content.append("=" * 60)
            content.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            content.append(f"Template: {state.form_template_path}")
            content.append("")
            
            # Group mappings by confidence level
            high_conf = [m for m in semantic_mappings if m.confidence >= 0.8]
            medium_conf = [m for m in semantic_mappings if 0.5 <= m.confidence < 0.8]
            low_conf = [m for m in semantic_mappings if m.confidence < 0.5]
            
            for confidence_group, title in [
                (high_conf, "HIGH CONFIDENCE FIELDS (≥80%)"),
                (medium_conf, "MEDIUM CONFIDENCE FIELDS (50-79%)"),
                (low_conf, "LOW CONFIDENCE FIELDS (<50%)")
            ]:
                if confidence_group:
                    content.append(title)
                    content.append("-" * 40)
                    
                    for mapping in confidence_group:
                        content.append(f"{mapping.form_field_name}: {mapping.extracted_value}")
                        content.append(f"  Type: {mapping.form_field_type} | Confidence: {mapping.confidence:.1%}")
                        content.append("")
            
            # Write to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            
            return SemanticFormFillingResult(
                output_file_path=output_path,
                semantic_mappings=semantic_mappings,
                success=True,
                total_form_fields=len(semantic_mappings),
                fields_filled=len(semantic_mappings)
            )
            
        except Exception as e:
            return SemanticFormFillingResult(
                output_file_path="",
                semantic_mappings=semantic_mappings,
                success=False,
                errors=[f"Text form creation error: {str(e)}"]
            )

    def _format_value_for_pdf_field(
        self, 
        value: Any, 
        semantic_field_type: str, 
        pdf_field_type: int
    ) -> str:
        """Format extracted value appropriately for PDF field."""
        
        if value is None:
            return ""
        
        # Convert to string
        str_value = str(value).strip()
        
        # Handle different field types - check for None first
        if semantic_field_type is None:
            return str_value
        elif semantic_field_type == 'date':
            # Try to standardize date format
            return self._standardize_date(str_value)
        elif semantic_field_type == 'checkbox' or semantic_field_type.startswith('radio'):
            # Handle checkbox/radio values
            return self._format_checkbox_value(str_value)
        elif semantic_field_type == 'email':
            return str_value.lower()
        else:
            return str_value

    def _standardize_date(self, date_str: str) -> str:
        """Standardize date format."""
        # Basic date standardization - could be enhanced
        if not date_str:
            return ""
        
        # If already in DD.MM.YYYY format, keep it
        if len(date_str.split('.')) == 3:
            return date_str
        
        # Otherwise return as-is
        return date_str

    def _format_checkbox_value(self, value_str: str) -> str:
        """Format checkbox/radio button values."""
        value_lower = value_str.lower()
        
        if value_lower in ['yes', 'ja', 'true', '1', 'x']:
            return "Yes"
        elif value_lower in ['no', 'nein', 'false', '0']:
            return "No"
        else:
            return value_str

    async def _save_semantic_mapping_report(
        self,
        semantic_mappings: List[SemanticFieldMapping],
        state: AgentState,
        output_path: str
    ) -> None:
        """Save detailed semantic mapping report for debugging and analysis."""
        
        try:
            # Create report data
            report_data = {
                "timestamp": datetime.now().isoformat(),
                "form_template": state.form_template_path,
                "source_documents": state.pdf_file_paths or [state.pdf_file_path],
                "total_semantic_mappings": len(semantic_mappings),
                "mapping_summary": {
                    "high_confidence": len([m for m in semantic_mappings if m.confidence >= 0.8]),
                    "medium_confidence": len([m for m in semantic_mappings if 0.5 <= m.confidence < 0.8]),
                    "low_confidence": len([m for m in semantic_mappings if m.confidence < 0.5])
                },
                "semantic_mappings": [asdict(mapping) for mapping in semantic_mappings]
            }
            
            # Save report
            report_filename = f"semantic_mapping_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            from src.config import config
            report_path = os.path.join(config.OUTPUT_DIR, report_filename)
            
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            
            print(f"📊 Semantic mapping report saved: {report_path}")
            
        except Exception as e:
            print(f"⚠️ Failed to save semantic mapping report: {str(e)}")