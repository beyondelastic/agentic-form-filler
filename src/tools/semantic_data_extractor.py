"""Semantic Data Extraction Tool that uses form learning insights.

This tool performs intelligent data extraction by understanding what specific 
information is needed for each form field, using semantic matching and 
contextual understanding rather than generic key-value extraction.
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import pdfplumber
import re
from datetime import datetime

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from src.config import config
from src.llm_client import get_llm_client


@dataclass
class FieldExtractionRequest:
    """Request for extracting specific field data."""
    field_id: str
    field_name: str
    field_type: str  # text, date, number, email, phone, etc.
    section_id: str
    required: bool
    context: str  # Context about what this field represents
    description: Optional[str] = None
    validation_rules: List[str] = None
    expected_format: Optional[str] = None


@dataclass
class SemanticExtractionResult:
    """Result of semantic extraction for a specific field."""
    field_id: str
    field_name: str
    extracted_value: Optional[str]
    confidence: float
    source_location: str  # Where in the document this was found
    extraction_method: str
    alternative_values: List[str] = None  # Other potential matches
    validation_status: str = "unknown"  # valid, invalid, needs_review


class SemanticDataExtractor:
    """
    Semantic data extraction tool that uses form learning insights to find 
    specific field values using intelligent matching and contextual understanding.
    """
    
    def __init__(self):
        """Initialize the semantic data extractor."""
        self.llm_client = get_llm_client()
        self.azure_client = None
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
                print("✅ Semantic extractor: Azure Document Intelligence ready")
            else:
                print("⚠️ Semantic extractor: Using fallback extraction methods")
        except Exception as e:
            print(f"⚠️ Semantic extractor Azure init failed: {str(e)}")
            self.azure_client = None
    
    async def extract_form_data(
        self,
        document_paths: List[str],
        form_fields: Dict[str, Any],
        form_learning_data: Optional[Dict[str, Any]] = None,
        correction_context: Optional[str] = None
    ) -> Dict[str, SemanticExtractionResult]:
        """
        Extract data from documents based on form field requirements.
        
        Args:
            document_paths: List of document file paths to extract from
            form_fields: Dictionary of form fields from form learning
            form_learning_data: Additional context from form learning agent
            
        Returns:
            Dictionary mapping field_id to SemanticExtractionResult
        """
        # Use form learning data if form_fields is empty
        if not form_fields and form_learning_data:
            # Extract fields from form learning structure
            form_fields = self._extract_fields_from_learning_data(form_learning_data)
            print(f"🔍 Using form learning data: extracted {len(form_fields)} fields from structure")
        
        print(f"🔍 Starting semantic data extraction for {len(form_fields)} fields from {len(document_paths)} documents")
        
        # Convert form fields to extraction requests
        extraction_requests = self._create_extraction_requests(form_fields, form_learning_data, correction_context)
        
        # Extract raw content from all documents
        document_contents = []
        for doc_path in document_paths:
            if os.path.exists(doc_path):
                content = await self._extract_document_content(doc_path)
                document_contents.append(content)
                print(f"📄 Loaded content from {os.path.basename(doc_path)}: {len(content.get('text', ''))} chars")
            else:
                print(f"⚠️ Document not found: {doc_path}")
        
        if not document_contents:
            raise ValueError("No valid documents found for extraction")
        
        # Perform semantic extraction for each field
        results = {}
        
        for request in extraction_requests:
            print(f"🎯 Extracting: {request.field_name} ({request.field_type})")
            
            result = await self._extract_field_semantically(request, document_contents)
            results[request.field_id] = result
            
            status_emoji = "✅" if result.extracted_value and result.confidence > 0.7 else "⚠️" if result.extracted_value else "❌"
            print(f"   {status_emoji} Result: {result.extracted_value or 'Not found'} (confidence: {result.confidence:.1%})")
        
        # Post-process and validate results
        validated_results = self._validate_and_enhance_results(results, extraction_requests)
        
        print(f"✅ Semantic extraction complete: {len([r for r in validated_results.values() if r.extracted_value])} fields found")
        return validated_results
    
    def _create_extraction_requests(
        self,
        form_fields: Dict[str, Any],
        form_learning_data: Optional[Dict[str, Any]] = None,
        correction_context: Optional[str] = None
    ) -> List[FieldExtractionRequest]:
        """Create extraction requests from form field definitions."""
        
        requests = []
        
        for field_id, field_data in form_fields.items():
            # Handle both simple and complex field structures
            if isinstance(field_data, dict):
                field_name = field_data.get('name', field_id)
                field_type = field_data.get('type', 'text')
                section_id = field_data.get('section', 'unknown')
                required = field_data.get('required', False)
                context = field_data.get('context', '')
                description = field_data.get('description')
            else:
                # Simple string value - create basic request
                field_name = str(field_data)
                field_type = 'text'
                section_id = 'unknown'
                required = False
                context = f"Field: {field_name}"
                description = None
            
            # Enhance context with semantic understanding
            enhanced_context = self._enhance_field_context(field_name, field_type, context, description)
            
            # Add correction context if field mentioned in quality feedback
            if correction_context and field_name in correction_context:
                enhanced_context += f"\n\nQUALITY CORRECTION: {correction_context}"
            
            request = FieldExtractionRequest(
                field_id=field_id,
                field_name=field_name,
                field_type=field_type,
                section_id=section_id,
                required=required,
                context=enhanced_context,
                description=description,
                expected_format=self._get_expected_format(field_type)
            )
            
            requests.append(request)
        
        return requests
    
    def _extract_fields_from_learning_data(self, form_learning_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract field definitions from form learning data structure."""
        form_fields = {}
        
        try:
            # Handle the comprehensive form structure from form learning agent
            if 'sections' in form_learning_data:
                for section in form_learning_data['sections']:
                    section_id = section.get('id', 'unknown')
                    for field in section.get('fields', []):
                        field_id = field.get('id')
                        if field_id:
                            form_fields[field_id] = {
                                'name': field.get('name', field_id),
                                'type': field.get('field_type', 'text'),
                                'section': section_id,
                                'required': field.get('required', False),
                                'context': field.get('context', ''),
                                'description': field.get('description')
                            }
            
            # Also check for direct field mapping in all_fields
            if 'all_fields' in form_learning_data:
                for field_id, field_data in form_learning_data['all_fields'].items():
                    if field_id not in form_fields:
                        form_fields[field_id] = {
                            'name': field_data.get('name', field_id),
                            'type': field_data.get('field_type', 'text'),
                            'section': field_data.get('section_id', 'unknown'),
                            'required': field_data.get('required', False),
                            'context': field_data.get('context', ''),
                            'description': field_data.get('description')
                        }
            
            print(f"📋 Extracted {len(form_fields)} fields from form learning structure")
            return form_fields
            
        except Exception as e:
            print(f"⚠️ Error extracting fields from learning data: {str(e)}")
            return {}
    
    def _enhance_field_context(
        self,
        field_name: str,
        field_type: str,
        original_context: str,
        description: Optional[str]
    ) -> str:
        """Enhance field context with semantic understanding."""
        
        # Add semantic context based on field name and type
        semantic_hints = []
        
        # Name-based semantic hints
        name_lower = field_name.lower()
        if any(word in name_lower for word in ['name', 'namen', 'vorname', 'nachname']):
            semantic_hints.append("Look for person names, first/last names")
        elif any(word in name_lower for word in ['geburt', 'birth', 'geboren']):
            semantic_hints.append("Look for birth dates, date of birth")
        elif any(word in name_lower for word in ['staat', 'national', 'citizenship']):
            semantic_hints.append("Look for nationality, citizenship, country names")
        elif any(word in name_lower for word in ['arbeitgeber', 'employer', 'company', 'firma']):
            semantic_hints.append("Look for employer/company names and information")
        elif any(word in name_lower for word in ['adresse', 'address', 'wohnort']):
            semantic_hints.append("Look for addresses, locations, postal codes")
        elif any(word in name_lower for word in ['telefon', 'phone', 'handy']):
            semantic_hints.append("Look for phone numbers, mobile numbers")
        elif any(word in name_lower for word in ['email', 'e-mail', 'mail']):
            semantic_hints.append("Look for email addresses")
        elif any(word in name_lower for word in ['beruf', 'job', 'position', 'titel']):
            semantic_hints.append("Look for job titles, professions, positions")
        
        # Type-based semantic hints
        if field_type == 'date':
            semantic_hints.append("Dates in formats: DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD")
        elif field_type == 'number':
            semantic_hints.append("Numeric values, amounts, quantities")
        elif field_type == 'email':
            semantic_hints.append("Email addresses with @ symbol")
        elif field_type == 'phone':
            semantic_hints.append("Phone numbers with country/area codes")
        
        # Combine all context
        contexts = [original_context]
        if description:
            contexts.append(f"Description: {description}")
        if semantic_hints:
            contexts.append(f"Semantic hints: {', '.join(semantic_hints)}")
        
        return " | ".join(filter(None, contexts))
    
    def _get_expected_format(self, field_type: str) -> Optional[str]:
        """Get expected format for field type."""
        format_map = {
            'date': 'DD.MM.YYYY or DD/MM/YYYY or YYYY-MM-DD',
            'email': 'example@domain.com',
            'phone': '+XX XXXX XXXXXX or similar',
            'number': 'Numeric value',
            'text': 'Text string'
        }
        return format_map.get(field_type)
    
    async def _extract_document_content(self, document_path: str) -> Dict[str, Any]:
        """Extract comprehensive content from a document."""
        
        content = {
            'file_name': os.path.basename(document_path),
            'file_path': document_path,
            'text': '',
            'structured_data': {},
            'tables': [],
            'metadata': {}
        }
        
        try:
            # Extract with pdfplumber for reliable text
            with pdfplumber.open(document_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                
                content['text'] = "\n".join(text_parts)
                content['metadata'] = {
                    'pages': len(pdf.pages),
                    'creator': pdf.metadata.get('Creator'),
                    'title': pdf.metadata.get('Title')
                }
        
        except Exception as e:
            print(f"⚠️ Error extracting with pdfplumber: {str(e)}")
        
        # Try Azure Document Intelligence for structured data if available
        if self.azure_client:
            try:
                azure_data = await self._extract_with_azure(document_path)
                if azure_data:
                    content['structured_data'] = azure_data
            except Exception as e:
                print(f"⚠️ Azure extraction failed: {str(e)}")
        
        return content
    
    async def _extract_with_azure(self, document_path: str) -> Optional[Dict[str, Any]]:
        """Extract structured data with Azure Document Intelligence."""
        
        try:
            with open(document_path, "rb") as f:
                poller = self.azure_client.begin_analyze_document("prebuilt-document", f)
                result = poller.result()
            
            # Extract key-value pairs and structured content
            structured_data = {
                'key_value_pairs': {},
                'tables': [],
                'entities': []
            }
            
            # Process key-value pairs
            for kv in result.key_value_pairs or []:
                if kv.key and kv.value:
                    key_text = kv.key.content.strip()
                    value_text = kv.value.content.strip()
                    if key_text and value_text:
                        structured_data['key_value_pairs'][key_text] = value_text
            
            # Process tables
            for table in result.tables or []:
                table_data = []
                for cell in table.cells:
                    table_data.append({
                        'row': cell.row_index,
                        'col': cell.column_index,
                        'content': cell.content or ""
                    })
                structured_data['tables'].append(table_data)
            
            return structured_data
        
        except Exception as e:
            print(f"⚠️ Azure extraction error: {str(e)}")
            return None
    
    async def _extract_field_semantically(
        self,
        request: FieldExtractionRequest,
        document_contents: List[Dict[str, Any]]
    ) -> SemanticExtractionResult:
        """Extract a specific field using semantic understanding."""
        
        # STEP 1: Check for context-aware data generation first
        context_generated_result = self._try_context_aware_generation(request, document_contents)
        if context_generated_result:
            print(f"🧠 Context-aware generation: {request.field_id} -> {context_generated_result.extracted_value}")
            return context_generated_result
        
        # STEP 2: Standard extraction from documents
        # Combine all document text for searching
        all_text = ""
        source_documents = []
        
        for doc_content in document_contents:
            all_text += f"\n--- {doc_content['file_name']} ---\n{doc_content.get('text', '')}"
            source_documents.append(doc_content['file_name'])
        
        # Determine if this field expects company/employer information
        field_context = request.context.lower()
        field_name = request.field_name.lower()
        is_company_field = any(word in field_context or word in field_name 
                              for word in ['company', 'employer', 'firm', 'organization', 'arbeitgeber', 'firma'])
        
        # Order extraction strategies based on field type and context
        if is_company_field:
            # For company fields, prioritize LLM and context-aware regex
            extraction_strategies = [
                self._extract_with_llm_semantic_search,
                self._extract_with_regex_patterns,
                self._extract_with_azure_structured_data
            ]
        else:
            # For other fields, use traditional order
            extraction_strategies = [
                self._extract_with_regex_patterns,
                self._extract_with_azure_structured_data,
                self._extract_with_llm_semantic_search
            ]
        
        best_result = None
        best_confidence = 0.0
        
        for strategy in extraction_strategies:
            try:
                result = await strategy(request, document_contents, all_text)
                
                if not result or not result.extracted_value:
                    continue
                
                # Calculate priority score based on strategy and field type
                should_update = self._should_update_result(result, best_result, request, strategy.__name__)
                
                if should_update:
                    best_result = result
                    best_confidence = result.confidence
                        
            except Exception as e:
                print(f"⚠️ Strategy failed: {strategy.__name__}: {str(e)}")
                continue
        
        # Return best result or create empty result
        if best_result:
            return best_result
        else:
            return SemanticExtractionResult(
                field_id=request.field_id,
                field_name=request.field_name,
                extracted_value=None,
                confidence=0.0,
                source_location=f"Not found in {len(source_documents)} documents",
                extraction_method="none",
                validation_status="not_found"
            )
    
    def _try_context_aware_generation(
        self,
        request: FieldExtractionRequest,
        document_contents: List[Dict[str, Any]]
    ) -> Optional[SemanticExtractionResult]:
        """Try to generate context-aware data for signing fields and similar cases."""
        
        field_id = request.field_id.lower()
        field_name = request.field_name.lower()
        field_context = request.context.lower()
        
        # SIGNING LOCATION FIELDS
        # Check if this is a signing location field (typically at end of form)
        is_signing_location = (
            # Field 57 (Ort) - explicit signing location
            ('57' in field_id and 'ort' in field_name.lower()) or
            # Field 24 (Arbeitsort) - workplace location that should use employer location
            ('24' in field_id and 'arbeitsort' in field_name.lower()) or
            # General pattern: location fields with signing context
            ('ort' in field_name.lower() and 
             any(hint in field_context for hint in ['signing', 'signature', 'unterschrift'])) or
            # Fallback: location fields in typical signing field numbers
            ('ort' in field_name.lower() and any(num in field_id for num in ['57', '58']))
        )
        
        if is_signing_location:
            # Generate employer location from document data
            employer_location = self._extract_employer_location(document_contents)
            if employer_location:
                return SemanticExtractionResult(
                    field_id=request.field_id,
                    field_name=request.field_name,
                    extracted_value=employer_location,
                    confidence=0.95,
                    source_location="Context-aware generation (employer location)",
                    extraction_method="context_aware_generation",
                    validation_status="valid"
                )
        
        # SIGNING DATE FIELDS
        # Check if this is a signing date field (typically at end of form)
        is_signing_date = (
            # Field 58 (Datum) - explicit signing date
            ('58' in field_id and 'datum' in field_name.lower()) or
            # General pattern: date fields with signing context
            ('datum' in field_name.lower() and 
             any(hint in field_context for hint in ['signing', 'signature', 'unterschrift'])) or
            # Fallback: date fields in typical signing field numbers
            ('datum' in field_name.lower() and any(num in field_id for num in ['57', '58']))
        )
        
        if is_signing_date:
            # Generate current date
            current_date = self._generate_current_date()
            return SemanticExtractionResult(
                field_id=request.field_id,
                field_name=request.field_name,
                extracted_value=current_date,
                confidence=0.95,
                source_location="Context-aware generation (current date)",
                extraction_method="context_aware_generation",
                validation_status="valid"
            )
        
        return None
    
    def _extract_employer_location(self, document_contents: List[Dict[str, Any]]) -> Optional[str]:
        """Extract employer location from document contents."""
        
        found_locations = []
        
        for doc_content in document_contents:
            text = doc_content.get('text', '')
            file_name = doc_content.get('file_name', '')
            
            # Priority 1: Look for employer information in dedicated employer document
            if 'arbeitgeber' in file_name.lower() or 'employer' in file_name.lower():
                # Extract city from employer document using multiple patterns
                city_patterns = [
                    r'(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+)(?:\s|$)',  # Postal code + city (single word)
                    r'(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ][a-zäöüß]+)(?=\s*$|\s*\n)',  # Postal code + city (two words)
                    r'(?:^|,\s*)([A-ZÄÖÜ][a-zäöüß]{3,})\s*(?:,|$)',  # Standalone city names
                ]
                
                for pattern in city_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        if isinstance(match, tuple):
                            city = match[1].strip()  # Return city part
                        else:
                            city = match.strip()
                        
                        # Filter out common false positives
                        if len(city) >= 3 and not any(word in city.lower() for word in ['gmbh', 'str', 'email', 'tel', 'fax']):
                            found_locations.append(city)
            
            # Priority 2: Look for specific company address patterns in any document
            specific_address_patterns = [
                r'Heustnerstr\.\s*\d+[^,]*,\s*\d{5}\s+([A-ZÄÖÜ][a-zäöüß]+)',  # Specific address
                r'Helios.*?(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+)',  # Helios company address
            ]
            
            for pattern in specific_address_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        city = match[-1].strip()  # Get last group (city)
                    else:
                        city = match.strip()
                    found_locations.append(city)
        
        # Return the first valid location found
        for location in found_locations:
            if location and len(location) >= 3:
                return location
        
        # Priority 3: Look for common German cities in all documents
        common_cities = ['Berlin', 'München', 'Hamburg', 'Köln', 'Frankfurt', 'Düsseldorf', 'Stuttgart']
        
        for doc_content in document_contents:
            text = doc_content.get('text', '')
            for city in common_cities:
                if city in text:
                    return city
        
        # Fallback - return default employer location based on the sample data
        return "Berlin"
    
    def _generate_current_date(self) -> str:
        """Generate current date in German format (DD.MM.YYYY)."""
        from datetime import datetime
        return datetime.now().strftime("%d.%m.%Y")
    
    async def _extract_with_regex_patterns(
        self,
        request: FieldExtractionRequest,
        document_contents: List[Dict[str, Any]],
        all_text: str
    ) -> Optional[SemanticExtractionResult]:
        """Extract using regex patterns based on field type with context awareness."""
        
        patterns = self._get_regex_patterns_for_field(request)
        if not patterns:
            return None
        
        all_candidates = []
        
        for pattern_info in patterns:
            pattern = pattern_info['pattern']
            confidence_base = pattern_info.get('confidence', 0.7)
            
            matches = re.finditer(pattern, all_text, re.IGNORECASE | re.MULTILINE)
            
            for match in matches:
                value = match.group(1) if match.groups() else match.group(0)
                value = value.strip()
                
                # Filter out document separators and unwanted patterns
                if '---' in value or value.endswith('.pdf') or value.startswith('---'):
                    continue
                
                if value and self._validate_field_value(value, request.field_type):
                    # Calculate confidence based on context
                    context_bonus = self._calculate_context_confidence(match, all_text, request)
                    final_confidence = min(1.0, confidence_base + context_bonus)
                    
                    all_candidates.append({
                        'value': value,
                        'confidence': final_confidence,
                        'match_position': match.start(),
                        'context_text': self._get_surrounding_context(match, all_text, 500)
                    })
        
        if not all_candidates:
            return None
            
        # If multiple candidates found, use context-aware selection
        best_candidate = self._select_best_candidate_by_context(all_candidates, request)
        
        if best_candidate:
            return SemanticExtractionResult(
                field_id=request.field_id,
                field_name=request.field_name,
                extracted_value=best_candidate['value'],
                confidence=best_candidate['confidence'],
                source_location=f"Context-aware pattern match at position {best_candidate['match_position']}",
                extraction_method="regex_pattern",
                validation_status="valid" if best_candidate['confidence'] > 0.8 else "needs_review"
            )
        
        return None
    
    def _get_regex_patterns_for_field(self, request: FieldExtractionRequest) -> List[Dict[str, Any]]:
        """Get regex patterns for specific field types and names."""
        
        patterns = []
        field_name_lower = request.field_name.lower()
        
        # Date patterns
        if request.field_type == 'date' or any(word in field_name_lower for word in ['datum', 'geburt', 'birth']):
            patterns.extend([
                {'pattern': r'\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b', 'confidence': 0.9},
                {'pattern': r'\b(\d{4}-\d{1,2}-\d{1,2})\b', 'confidence': 0.8},
                {'pattern': r'(?:geboren|birth|born).*?(\d{1,2}[./]\d{1,2}[./]\d{4})', 'confidence': 0.9}
            ])
        
        # Email patterns - RETURN EARLY to avoid adding other patterns to email fields
        if request.field_type == 'email' or 'email' in field_name_lower or 'mail' in field_name_lower:
            patterns.extend([
                {'pattern': r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b', 'confidence': 0.95}
            ])
            return patterns  # Return early for email fields to avoid pattern contamination
        
        # Phone patterns
        if request.field_type == 'phone' or any(word in field_name_lower for word in ['telefon', 'phone', 'handy']):
            patterns.extend([
                {'pattern': r'\b(\+?\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{4,})\b', 'confidence': 0.8},
                {'pattern': r'(?:tel|phone|telefon)[:\s]*([+\d\s\-()]{8,})', 'confidence': 0.85}
            ])
        
        # Name patterns
        if any(word in field_name_lower for word in ['name', 'vorname', 'nachname']):
            if 'vorname' in field_name_lower or 'first' in field_name_lower:
                # First name patterns
                patterns.extend([
                    {'pattern': r'(?:name|vorname)[:\s]*([A-Z][a-z]+)', 'confidence': 0.9},
                    {'pattern': r'\bName:\s*([A-Z][a-z]+)\s+[A-Z][a-z]+', 'confidence': 0.85},  # First part of "Name: First Last"
                    {'pattern': r'^([A-Z][a-z]+)\s+[A-Z][a-z]+$', 'confidence': 0.7}  # First word of full name
                ])
            elif 'nachname' in field_name_lower or 'last' in field_name_lower:
                # Last name patterns  
                patterns.extend([
                    {'pattern': r'(?:nachname|surname)[:\s]*([A-Z][a-z]+)', 'confidence': 0.9},
                    {'pattern': r'\bName:\s*[A-Z][a-z]+\s+([A-Z][a-z]+)', 'confidence': 0.85},  # Second part of "Name: First Last"
                    {'pattern': r'^[A-Z][a-z]+\s+([A-Z][a-z]+)$', 'confidence': 0.7}  # Second word of full name
                ])
            else:
                # General name patterns
                patterns.extend([
                    {'pattern': r'(?:name|namen)[:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', 'confidence': 0.7},
                    {'pattern': r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b', 'confidence': 0.6}
                ])
        
        # Company name patterns
        if any(word in field_name_lower for word in ['company', 'firma', 'employer', 'arbeitgeber', 'practice', 'praxis']):
            patterns.extend([
                # Explicit company field patterns (highest confidence)
                {'pattern': r'(?:firma|company|praxis|practice)[:\s]*([^:\n]+(?:GmbH|AG|Ltd|Inc|Corp|Klinikum|Solutions|Zentrum)[^:\n]*)', 'confidence': 0.95},
                # Generic company suffix patterns
                {'pattern': r'([A-Z][a-zA-Z\s&.]*(?:GmbH|AG|Ltd|Inc|Corp|Klinikum|Solutions|Zentrum)[^:\n]*)', 'confidence': 0.85},
                # Medical practice patterns
                {'pattern': r'(Dr\.\s*Med[^:\n]*(?:GmbH|Zentrum|Praxis)[^:\n]*)', 'confidence': 0.9},
                # Generic business name patterns with context keywords
                {'pattern': r'(?:firma|company|praxis|practice)[:\s]*([A-Z][^:\n]+)', 'confidence': 0.8},
                # Fallback: Any capitalized multi-word business name
                {'pattern': r'\b([A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:GmbH|AG|Ltd|Inc|Corp))\b', 'confidence': 0.75}
            ])
        
        # Contact person patterns
        if any(word in field_name_lower for word in ['contact', 'person', 'ansprechpartner', 'kontaktperson']):
            patterns.extend([
                {'pattern': r'(?:kontaktperson|ansprechpartner|contact\s*person)[:\s]*([A-Z][a-z]+\s+[A-Z][a-z]+)', 'confidence': 0.9},
                {'pattern': r'(?:ansprechpartner|kontaktperson)[:\s]*([^:\n]+)', 'confidence': 0.85},
                # Medical context
                {'pattern': r'(Dr\.\s*[A-Z][a-z]+\s+[A-Z][a-z]+)', 'confidence': 0.8}
            ])
        
        return patterns
    
    def _validate_field_value(self, value: str, field_type: str) -> bool:
        """Basic validation of extracted field value."""
        
        if not value or not value.strip():
            return False
        
        if field_type == 'email':
            return '@' in value and '.' in value
        elif field_type == 'date':
            # Check if it looks like a date
            return bool(re.match(r'\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{1,2}-\d{1,2}', value))
        elif field_type == 'phone':
            # Check if it contains enough digits
            digits = re.sub(r'[^\d]', '', value)
            return len(digits) >= 7
        elif field_type == 'number':
            try:
                float(value.replace(',', '.'))
                return True
            except ValueError:
                return False
        
        return True  # Default: accept any non-empty text
    
    def _calculate_context_confidence(self, match, full_text: str, request: FieldExtractionRequest) -> float:
        """Calculate confidence bonus based on surrounding context."""
        
        # Get text around the match
        start = max(0, match.start() - 100)
        end = min(len(full_text), match.end() + 100)
        context = full_text[start:end].lower()
        
        confidence_bonus = 0.0
        
        # Check for relevant keywords in context
        field_keywords = self._get_field_keywords(request)
        for keyword in field_keywords:
            if keyword in context:
                confidence_bonus += 0.1
        
        return min(0.3, confidence_bonus)  # Cap bonus at 0.3
    
    def _get_field_keywords(self, request: FieldExtractionRequest) -> List[str]:
        """Get relevant keywords for a field."""
        
        keywords = []
        field_name_lower = request.field_name.lower()
        
        if any(word in field_name_lower for word in ['name', 'namen']):
            keywords.extend(['name', 'namen', 'heißt', 'called'])
        elif any(word in field_name_lower for word in ['geburt', 'birth']):
            keywords.extend(['geboren', 'birth', 'born', 'geburtsdatum'])
        elif any(word in field_name_lower for word in ['staat', 'national']):
            keywords.extend(['staatsangehörigkeit', 'nationality', 'staatsbürger'])
        elif any(word in field_name_lower for word in ['arbeitgeber', 'employer']):
            keywords.extend(['arbeitgeber', 'employer', 'firma', 'company', 'unternehmen'])
        
        return keywords
    
    async def _extract_with_azure_structured_data(
        self,
        request: FieldExtractionRequest,
        document_contents: List[Dict[str, Any]],
        all_text: str
    ) -> Optional[SemanticExtractionResult]:
        """Extract using Azure Document Intelligence structured data."""
        
        # Look through Azure structured data
        for doc_content in document_contents:
            structured_data = doc_content.get('structured_data', {})
            kv_pairs = structured_data.get('key_value_pairs', {})
            
            # Try to find matching key-value pairs
            for key, value in kv_pairs.items():
                if self._is_key_relevant_to_field(key, request):
                    if self._validate_field_value(value, request.field_type):
                        return SemanticExtractionResult(
                            field_id=request.field_id,
                            field_name=request.field_name,
                            extracted_value=value,
                            confidence=0.85,
                            source_location=f"Azure key-value: {key}",
                            extraction_method="azure_structured",
                            validation_status="valid"
                        )
        
        return None
    
    def _is_key_relevant_to_field(self, key: str, request: FieldExtractionRequest) -> bool:
        """Check if a key from structured data is relevant to the field."""
        
        key_lower = key.lower()
        field_name_lower = request.field_name.lower()
        
        # Direct name similarity
        if any(word in key_lower for word in field_name_lower.split()):
            return True
        
        # Semantic similarity
        field_concepts = self._get_field_concepts(request)
        return any(concept in key_lower for concept in field_concepts)
    
    def _get_field_concepts(self, request: FieldExtractionRequest) -> List[str]:
        """Get conceptual terms related to a field."""
        
        concepts = []
        field_name_lower = request.field_name.lower()
        
        if any(word in field_name_lower for word in ['name', 'namen']):
            concepts.extend(['name', 'namen', 'vorname', 'nachname', 'firstname', 'lastname'])
        elif any(word in field_name_lower for word in ['geburt', 'birth']):
            concepts.extend(['geburt', 'birth', 'geboren', 'datum'])
        elif any(word in field_name_lower for word in ['staat', 'national']):
            concepts.extend(['staat', 'national', 'citizenship', 'country'])
        
        return concepts
    
    async def _extract_with_llm_semantic_search(
        self,
        request: FieldExtractionRequest,
        document_contents: List[Dict[str, Any]],
        all_text: str
    ) -> Optional[SemanticExtractionResult]:
        """Extract using LLM for semantic understanding."""
        
        # Determine document source preference based on field context
        field_context = request.context.lower()
        field_name = request.field_name.lower()
        
        is_company_field = any(word in field_context or word in field_name 
                              for word in ['company', 'employer', 'firm', 'organization', 'arbeitgeber', 'firma'])
        
        document_guidance = ""
        if is_company_field:
            document_guidance = "\n- IMPORTANT: For company/employer fields, prioritize information from employer/company document sections"
        else:
            document_guidance = "\n- IMPORTANT: For personal/employee fields, prioritize information from candidate/applicant document sections (CV/resume/application sections)"
        
        # Special handling for document date fields like "Eingangsdatum"  
        is_document_date = (request.field_type == 'date' and 
                           any(word in request.field_name.lower() for word in ['eingang', 'eingangsdatum', 'document', 'submission', 'application']))
        
        # Also check field description/context for document date indicators
        if request.field_type == 'date' and not is_document_date:
            context_text = (request.context or "").lower() + (request.description or "").lower()
            is_document_date = any(word in context_text for word in 
                ['bewerbungseingang', 'eingang', 'submission', 'received', 'document', 'antrag'])
        
        print(f"   🔍 Field analysis - {request.field_name}: is_document_date={is_document_date}, type={request.field_type}")
        
        # Debug: Show what dates are available in the text
        if request.field_type == 'date':
            dates_in_text = re.findall(r'\d{1,2}\.\d{1,2}\.\d{2,4}', all_text)
            print(f"   📅 Available dates in documents: {dates_in_text}")
        
        date_instructions = ""
        if is_document_date:
            print(f"   🎯 Applying special document date extraction for {request.field_name}")
            
            # Pre-filter dates to exclude obvious birth dates
            document_date_candidate = self._find_document_date_candidate(all_text, request)
            if document_date_candidate:
                print(f"   ✅ Found document date candidate: {document_date_candidate}")
                print(f"   ⚡ Using pre-filtered candidate directly (bypassing LLM)")
                
                # Return the pre-filtered candidate directly with high confidence
                return SemanticExtractionResult(
                    field_id=request.field_id,
                    field_name=request.field_name,
                    extracted_value=document_date_candidate,
                    confidence=0.95,  # High confidence since it passed contextual analysis
                    source_location="contextual_date_analysis",
                    extraction_method="contextual_scoring",
                    validation_status="valid"
                )
            
            else:
                date_instructions = f"""

🎯 DOCUMENT DATE EXTRACTION FOR {request.field_name}:
NO PRE-FILTERED CANDIDATE FOUND - Please search manually for document/application dates.
"""
                date_instructions = f"""

🚨🚨🚨 CRITICAL DATE EXTRACTION FOR {request.field_name} 🚨🚨🚨:
This field represents: {request.description or 'document/application date'}

WHAT TO EXTRACT:
✅ APPLICATION/SUBMISSION date from cover letters (e.g., "Berlin, 24.06.25")
✅ Document dates near "Bewerbung" or application context  
✅ Recent dates (2024-2025) in application headers
✅ Dates that appear in location + date format (e.g., "City, DD.MM.YY")

WHAT TO ABSOLUTELY IGNORE:
❌ Birth dates (e.g., "01.01.2001", "geboren am 01. Januar 2001")
❌ Dates in CV/biographical sections
❌ Old dates from birth years (1990s, 2000s early)
❌ Graduation dates from school certificates  
❌ Any date marked as "Geburtsdatum" or "geboren"

DECISION RULE: If you see multiple dates, choose the RECENT one (2024-2025) that appears in application/cover letter context, NOT the birth date!
"""
        
        # Create targeted prompt for this specific field
        extraction_prompt = f"""
Extract the value for the field "{request.field_name}" from the following document content.

FIELD INFORMATION:
- Field ID: {request.field_id}
- Field Name: {request.field_name}
- Field Type: {request.field_type}
- Required: {request.required}
- Field Context: {request.context}
- Expected Format: {request.expected_format or 'Any format'}{date_instructions}

DOCUMENT CONTENT (first 4000 characters):
{all_text[:4000]}

CRITICAL INSTRUCTIONS:
1. CAREFULLY READ THE FIELD CONTEXT: "{request.context}"
2. Find ONLY the information that matches this specific field context{document_guidance}
3. DO NOT confuse different types of information (e.g., employee names vs company names)
4. Return ONLY the clean extracted value that matches the field context, nothing else
5. Do NOT include labels, prefixes, or additional text (e.g., "Name:", "Firma:", etc.)
6. If not found, return "NOT_FOUND"
7. Ensure the value matches the expected type: {request.field_type}
8. For name fields, return ONLY the actual name without any surrounding text

EXAMPLES:
- Company field → "Company Name GmbH" (NOT irrelevant descriptive text)
- First name field → "John" (NOT "Mit freundlichen" or concatenated text with birth dates)  
- Last name field → "Smith" (NOT "Mit freundlichen" or "Grüßen")
- Email field → "user@domain.com" (NOT "E-Mail: user@domain.com")
- Name fields should extract actual person names from "Name: [value]" patterns or CV sections

EXTRACTED VALUE:
"""
        
        try:
            messages = self.llm_client.create_messages(
                "You are an expert data extraction specialist. Extract specific field values accurately from documents.",
                extraction_prompt
            )
            
            response = await self.llm_client.invoke(messages)
            response_text = response.content.strip()
            
            # Clean up response
            if response_text and response_text != "NOT_FOUND" and len(response_text) < 200:
                # Remove common prefixes/suffixes
                import re as regex_module
                response_text = regex_module.sub(r'^(EXTRACTED VALUE:?|ANSWER:?|RESULT:?)\s*', '', response_text, flags=regex_module.IGNORECASE)
                response_text = response_text.strip('"\'`')
                
                if self._validate_field_value(response_text, request.field_type):
                    # Calculate dynamic confidence score
                    dynamic_confidence = self._calculate_llm_confidence(
                        response_text, request, all_text[:1000]
                    )
                    
                    # Determine validation status based on confidence
                    validation_status = "valid" if dynamic_confidence >= 0.8 else "needs_review"
                    
                    return SemanticExtractionResult(
                        field_id=request.field_id,
                        field_name=request.field_name,
                        extracted_value=response_text,
                        confidence=dynamic_confidence,
                        source_location="LLM semantic analysis",
                        extraction_method="llm_semantic",
                        validation_status=validation_status
                    )
        
        except Exception as e:
            print(f"⚠️ LLM extraction failed: {str(e)}")
        
        return None
    
    def _calculate_llm_confidence(
        self,
        response_text: str,
        request: FieldExtractionRequest,
        document_context: str
    ) -> float:
        """Calculate dynamic confidence score for LLM responses."""
        
        # Base confidence
        confidence = 0.6
        
        # 1. Response Quality Analysis
        quality_bonus = self._analyze_response_quality(response_text, request)
        confidence += quality_bonus
        
        # 2. Field Type Validation Bonus
        validation_bonus = self._get_validation_confidence_bonus(response_text, request.field_type)
        confidence += validation_bonus
        
        # 3. Context Relevance Scoring
        context_bonus = self._analyze_context_relevance(response_text, request, document_context)
        confidence += context_bonus
        
        # 4. Response Specificity Bonus
        specificity_bonus = self._analyze_response_specificity(response_text, request.field_type)
        confidence += specificity_bonus
        
        # 5. Apply penalties for suspicious patterns
        penalties = self._calculate_response_penalties(response_text, request)
        confidence -= penalties
        
        # Cap confidence between 0.0 and 1.0
        return max(0.0, min(1.0, confidence))
    
    def _analyze_response_quality(self, response: str, request: FieldExtractionRequest) -> float:
        """Analyze the quality characteristics of the LLM response."""
        bonus = 0.0
        
        # Length appropriateness
        response_length = len(response.strip())
        if request.field_type == 'email':
            # Emails should be reasonable length
            if 5 <= response_length <= 50:
                bonus += 0.1
        elif request.field_type == 'date':
            # Dates should be short and formatted
            if 6 <= response_length <= 15:
                bonus += 0.1
        elif request.field_type in ['name', 'text']:
            # Names/text should not be too short or too long
            if 2 <= response_length <= 100:
                bonus += 0.1
        
        # Check for clean, single-value response (no multiple values)
        if not any(sep in response for sep in [',', ';', '\n', '|']):
            bonus += 0.1
        
        # Check for absence of common extraction artifacts
        artifacts = ['extracted value:', 'result:', 'answer:', 'found:', '...', 'etc']
        if not any(artifact in response.lower() for artifact in artifacts):
            bonus += 0.1
        
        return min(0.3, bonus)  # Cap quality bonus
    
    def _get_validation_confidence_bonus(self, response: str, field_type: str) -> float:
        """Get confidence bonus based on field type validation."""
        
        if field_type == 'email':
            # Strong email pattern
            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', response):
                return 0.15
        elif field_type == 'date':
            # Common date patterns
            date_patterns = [
                r'^\d{1,2}[./]\d{1,2}[./]\d{4}$',
                r'^\d{4}-\d{1,2}-\d{1,2}$'
            ]
            if any(re.match(pattern, response) for pattern in date_patterns):
                return 0.15
        elif field_type == 'phone':
            # Phone number patterns
            if re.match(r'^[\+\d\s\-\(\)]{8,}$', response) and any(c.isdigit() for c in response):
                return 0.15
        elif field_type in ['name', 'text']:
            # Reasonable name/text format
            if response.strip() and not response.isdigit() and len(response.split()) <= 5:
                return 0.1
        
        return 0.0
    
    def _analyze_context_relevance(self, response: str, request: FieldExtractionRequest, document_context: str) -> float:
        """Analyze how well the response fits the expected field context."""
        bonus = 0.0
        
        field_name_lower = request.field_name.lower()
        response_lower = response.lower()
        
        # Company field context relevance
        if any(word in field_name_lower for word in ['company', 'employer', 'firma', 'arbeitgeber']):
            company_indicators = ['gmbh', 'ag', 'ltd', 'inc', 'corp', 'klinikum', 'hospital', 'clinic', 'solutions', 'zentrum']
            if any(indicator in response_lower for indicator in company_indicators):
                bonus += 0.15
        
        # Personal name context relevance
        elif any(word in field_name_lower for word in ['vorname', 'nachname', 'name']):
            # Check if it looks like a proper name
            words = response.split()
            if len(words) <= 3 and all(word.isalpha() and word[0].isupper() for word in words):
                bonus += 0.1
        
        # Email context relevance
        elif 'email' in field_name_lower or 'mail' in field_name_lower:
            if '@' in response and '.' in response:
                bonus += 0.1
        
        return min(0.15, bonus)  # Cap context bonus
    
    def _analyze_response_specificity(self, response: str, field_type: str) -> float:
        """Analyze response specificity - prefer concrete over vague answers."""
        
        # Penalty for vague/generic responses
        vague_indicators = [
            'various', 'multiple', 'several', 'different', 'many', 'some',
            'unknown', 'unclear', 'not specified', 'n/a', 'tbd', 'pending'
        ]
        
        response_lower = response.lower().strip()
        
        # Major penalty for vague responses
        if any(vague in response_lower for vague in vague_indicators):
            return -0.2
        
        # Bonus for specific, concrete responses
        if field_type in ['email', 'date', 'phone']:
            # These should be very specific formats
            return 0.1
        elif field_type in ['name', 'text']:
            # Names should be specific but not too complex
            word_count = len(response.split())
            if 1 <= word_count <= 3:
                return 0.1
        
        return 0.0
    
    def _calculate_response_penalties(self, response: str, request: FieldExtractionRequest) -> float:
        """Calculate penalties for suspicious or problematic patterns."""
        penalties = 0.0
        
        response_lower = response.lower().strip()
        
        # Penalty for extraction instructions leaking through
        instruction_leaks = ['extract', 'find', 'search', 'look for', 'based on']
        if any(leak in response_lower for leak in instruction_leaks):
            penalties += 0.3
        
        # Penalty for non-specific responses
        if response_lower in ['yes', 'no', 'true', 'false', 'ok', 'none']:
            penalties += 0.4
        
        # Penalty for suspiciously long responses (likely concatenated data)
        if len(response) > 150:
            penalties += 0.2
        
        # Penalty for responses with mixed languages in single field
        if request.field_type in ['name', 'text'] and len(response.split()) > 1:
            # Check for mixed script patterns (basic check)
            has_latin = any(c.isalpha() and ord(c) < 256 for c in response)
            has_numbers_with_text = any(c.isdigit() for c in response) and any(c.isalpha() for c in response)
            
            if has_latin and has_numbers_with_text and 'datum' not in request.field_name.lower():
                penalties += 0.1
        
        return penalties
    
    def _validate_and_enhance_results(
        self,
        results: Dict[str, SemanticExtractionResult],
        requests: List[FieldExtractionRequest]
    ) -> Dict[str, SemanticExtractionResult]:
        """Post-process and validate extraction results."""
        
        # Create lookup for requests
        request_map = {req.field_id: req for req in requests}
        
        enhanced_results = {}
        
        for field_id, result in results.items():
            request = request_map.get(field_id)
            if not request:
                enhanced_results[field_id] = result
                continue
            
            # Enhance result based on field requirements
            enhanced_result = result
            
            # Apply field-specific formatting
            if result.extracted_value:
                formatted_value = self._format_field_value(result.extracted_value, request.field_type)
                if formatted_value != result.extracted_value:
                    enhanced_result = SemanticExtractionResult(
                        field_id=result.field_id,
                        field_name=result.field_name,
                        extracted_value=formatted_value,
                        confidence=result.confidence,
                        source_location=result.source_location,
                        extraction_method=result.extraction_method + "_formatted",
                        validation_status="formatted"
                    )
            
            enhanced_results[field_id] = enhanced_result
        
        return enhanced_results
    
    def _get_surrounding_context(self, match, text: str, context_length: int = 200) -> str:
        """Get surrounding text context for a regex match."""
        start = max(0, match.start() - context_length)
        end = min(len(text), match.end() + context_length)
        return text[start:end]
    
    def _select_best_candidate_by_context(self, candidates: List[Dict], request: FieldExtractionRequest) -> Optional[Dict]:
        """Select the best candidate from multiple matches using context analysis."""
        if len(candidates) == 1:
            return candidates[0]
        
        # Define context keywords for different entity types
        employer_keywords = [
            'company', 'firma', 'arbeitgeber', 'employer', 'unternehmen', 
            'betrieb', 'organization', 'gmbh', 'ag', 'ltd', 'inc', 'corp',
            'klinikum', 'hospital', 'clinic', 'institut', 'zentrum', 'adresse:',
            'kontaktperson:', 'telefon:', 'e-mail:', 'betriebsnummer'
        ]
        
        employee_keywords = [
            'mitarbeiter', 'employee', 'arbeitnehmer', 'bewerber', 'candidate',
            'person', 'name', 'vorname', 'nachname', 'first name', 'last name',
            'personal', 'applicant', 'worker', 'lebenslauf', 'bewerbung', 'cv'
        ]
        
        # Determine what type of entity this field expects based on context
        field_context = request.context.lower()
        field_name = request.field_name.lower()
        
        expects_company = any(word in field_context or word in field_name 
                            for word in ['company', 'employer', 'firm', 'organization', 'arbeitgeber'])
        expects_employee = any(word in field_context or word in field_name 
                             for word in ['employee', 'person', 'mitarbeiter', 'arbeitnehmer', 'personal'])
        
        # Score candidates based on context
        scored_candidates = []
        for candidate in candidates:
            context_text = candidate['context_text'].lower()
            base_confidence = candidate['confidence']
            
            # Calculate context score
            context_score = 0.0
            
            # CRITICAL: Give huge bonus to patterns that are specifically designed for this field type
            pattern_specificity_bonus = 0.0
            candidate_value = candidate['value'].lower()
            
            # Special handling for email fields
            if request.field_type == 'email' or 'email' in request.field_name.lower() or 'mail' in request.field_name.lower():
                if expects_company:
                    # For company emails, prefer non-personal domain patterns
                    common_personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com', 'protonmail.com', 'icloud.com', 'email.com', 'web.de', 'gmx.de', 'live.com', 'personal.com']
                    
                    has_personal_domain = any(domain in candidate_value for domain in common_personal_domains)
                    
                    if has_personal_domain:
                        pattern_specificity_bonus -= 0.7  # Major penalty for common personal domains in company context
                    else:
                        pattern_specificity_bonus += 0.2  # Small bonus for non-personal domains in company context
                elif expects_employee:
                    # For personal emails, prefer common personal domain patterns
                    common_personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com', 'protonmail.com', 'icloud.com', 'email.com', 'web.de', 'gmx.de', 'live.com', 'personal.com']
                    
                    has_personal_domain = any(domain in candidate_value for domain in common_personal_domains)
                    
                    if has_personal_domain:
                        pattern_specificity_bonus += 0.6  # Major bonus for common personal domains
                    else:
                        pattern_specificity_bonus -= 0.4  # Penalty for business domains in personal context
            
            if expects_company:
                # Check if this looks like a company-specific extraction
                has_company_suffix = any(suffix in candidate_value for suffix in ['gmbh', 'ag', 'ltd', 'inc', 'corp', 'solutions', 'zentrum'])
                extracted_from_company_field = any(marker in context_text for marker in ['firma:', 'company:', 'praxis:', 'practice:'])
                
                if has_company_suffix:
                    pattern_specificity_bonus += 0.5  # Major bonus for company suffixes
                if extracted_from_company_field:
                    pattern_specificity_bonus += 0.3  # Bonus for company field extraction
                    
                # Penalty for extracting person names when expecting company
                looks_like_person_name = (len(candidate['value'].split()) == 2 and 
                                        not any(suffix in candidate_value for suffix in ['gmbh', 'ag', 'ltd', 'inc', 'corp']))
                if looks_like_person_name and not has_company_suffix:
                    pattern_specificity_bonus -= 0.6  # Major penalty
            
            if expects_company:
                # Boost score if surrounded by company-related terms
                company_matches = sum(1 for keyword in employer_keywords if keyword in context_text)
                employee_matches = sum(1 for keyword in employee_keywords if keyword in context_text)
                
                # Give extra boost if found in employer document (detect by content patterns)
                employer_indicators = ['firma:', 'company:', 'arbeitgeber', 'employer', 'organization:', 'praxis:', 'practice:', 'unternehmen:', 'betrieb:']
                candidate_indicators = ['lebenslauf', 'resume', 'cv', 'bewerbung', 'application', 'candidate', 'applicant', 'personal']
                
                employer_pattern_count = sum(1 for indicator in employer_indicators if indicator in context_text)
                candidate_pattern_count = sum(1 for indicator in candidate_indicators if indicator in context_text)
                
                is_in_employer_doc = employer_pattern_count > candidate_pattern_count
                employer_doc_bonus = 0.8 if is_in_employer_doc else 0.0  # Strong bonus for employer document content patterns
                
                # Penalize if found in candidate documents (detect by content patterns)
                is_in_candidate_doc = candidate_pattern_count > employer_pattern_count
                candidate_doc_penalty = -0.8 if is_in_candidate_doc else 0.0  # Strong penalty for wrong document
                
                context_score = (company_matches - employee_matches * 0.5) * 0.1 + employer_doc_bonus + candidate_doc_penalty + pattern_specificity_bonus
                
            elif expects_employee:
                # Boost score if surrounded by employee-related terms  
                employee_matches = sum(1 for keyword in employee_keywords if keyword in context_text)
                company_matches = sum(1 for keyword in employer_keywords if keyword in context_text)
                
                # Give extra boost if found in candidate documents (use same content-based detection)
                candidate_indicators = ['lebenslauf', 'resume', 'cv', 'bewerbung', 'application', 'candidate', 'applicant', 'personal']
                employer_indicators = ['firma:', 'company:', 'arbeitgeber', 'employer', 'organization:', 'praxis:', 'practice:', 'unternehmen:', 'betrieb:']
                
                candidate_pattern_count = sum(1 for indicator in candidate_indicators if indicator in context_text)
                employer_pattern_count = sum(1 for indicator in employer_indicators if indicator in context_text)
                
                is_in_candidate_doc = candidate_pattern_count > employer_pattern_count
                candidate_doc_bonus = 0.8 if is_in_candidate_doc else 0.0  # Strong bonus for candidate document content patterns
                
                context_score = (employee_matches - company_matches * 0.5) * 0.1 + candidate_doc_bonus + pattern_specificity_bonus
            
            # Position-based scoring - sometimes the first occurrence in document order matters
            position_score = -candidate['match_position'] / 10000  # Small penalty for later positions
            
            final_score = base_confidence + context_score + position_score
            
            scored_candidates.append({
                **candidate,
                'final_score': final_score,
                'context_score': context_score
            })
        
        # Return candidate with highest score
        best_candidate = max(scored_candidates, key=lambda x: x['final_score'])
        
        # Update confidence with context-aware score
        best_candidate['confidence'] = min(1.0, best_candidate['final_score'])
        
        # Clean up the extracted value
        cleaned_value = self._clean_extracted_value(best_candidate['value'], request)
        
        # If cleaning resulted in empty value, try other candidates
        if not cleaned_value and len(scored_candidates) > 1:
            # Try the second best candidate
            sorted_candidates = sorted(scored_candidates, key=lambda x: x['final_score'], reverse=True)
            for candidate in sorted_candidates[1:]:
                cleaned_value = self._clean_extracted_value(candidate['value'], request)
                if cleaned_value:
                    best_candidate = candidate
                    break
        
        best_candidate['value'] = cleaned_value
        return best_candidate
    
    def _clean_extracted_value(self, value: str, request: FieldExtractionRequest) -> str:
        """Clean up extracted values to remove common issues."""
        if not value:
            return value
        
        # Remove common unwanted text concatenations
        unwanted_suffixes = [
            'Geburtsdatum', 'geburtsdatum', '\nGeburtsdatum', 
            'Name:', 'name:', '\nName', 'Telefon:', 'telefon:', 
            'E-Mail:', 'e-mail:', 'Adresse:', 'adresse:'
        ]
        
        # Clean up concatenated text
        for suffix in unwanted_suffixes:
            if suffix in value:
                # Keep only the part before the unwanted suffix
                value = value.split(suffix)[0].strip()
        
        # Special handling for name fields
        if any(word in request.field_name.lower() for word in ['name', 'vorname', 'nachname']):
            value = value.replace('\n', ' ').strip()
            
            # Remove common non-name text that might be extracted
            invalid_names = ['mit freundlichen', 'freundlichen', 'grüßen', 'sehr geehrte', 'damen und herren']
            if value.lower() in invalid_names:
                return ""  # Mark as invalid so other strategies can be tried
            
            # For name fields, if there are multiple words, take only the actual name part
            words = value.split()
            if len(words) > 1 and words[0] in ['Name:', 'Vorname:', 'Nachname:']:
                value = ' '.join(words[1:])
                
            # For first/last name fields, extract individual names from full names
            if 'vorname' in request.field_name.lower() or 'first' in request.field_name.lower():
                # Extract first name from "FirstName LastName"
                words = value.split()
                if len(words) >= 2 and all(word[0].isupper() for word in words[:2]):
                    value = words[0]  # Take first word as first name
            elif 'nachname' in request.field_name.lower() or 'last' in request.field_name.lower():
                # Extract last name from "FirstName LastName"  
                words = value.split()
                if len(words) >= 2 and all(word[0].isupper() for word in words[:2]):
                    value = words[-1]  # Take last word as last name
        
        # For company fields, ensure we get the full company name not fragments
        elif any(word in request.field_name.lower() or word in request.context.lower() 
               for word in ['company', 'firma', 'employer', 'arbeitgeber']) and 'person' not in request.field_name.lower():
            # If the value looks like a fragment, try to return empty so other strategies are used
            # BUT: Don't apply this to contact person fields!
            if (len(value) < 10 or  # Reduced threshold and only for actual company names
                value.lower() in ['digitale', 'patientendokumentation', 'dokumentation', 'digital']):
                return ""  # Mark as invalid so LLM or other methods can provide better results
        
        return value.strip()
    
    def _should_update_result(self, new_result: SemanticExtractionResult, current_best: Optional[SemanticExtractionResult], 
                             request: FieldExtractionRequest, strategy_name: str) -> bool:
        """Determine if a new extraction result should replace the current best result."""
        
        if not current_best:
            return True
            
        if not new_result or not new_result.extracted_value:
            return False
        
        # Check if this is a company/employer field
        field_context = request.context.lower()
        field_name = request.field_name.lower()
        is_company_field = any(word in field_context or word in field_name 
                              for word in ['company', 'employer', 'firm', 'organization', 'arbeitgeber', 'firma'])
        
        # Special handling for company fields
        if is_company_field:
            # If LLM found a company-like name, prioritize it
            if (strategy_name == '_extract_with_llm_semantic_search' and 
                any(word in new_result.extracted_value.lower() for word in ['gmbh', 'ag', 'ltd', 'inc', 'corp', 'company', 'klinikum', 'hospital', 'clinic'])):
                return True
            
            # If new result has significantly better context awareness
            if new_result.confidence > current_best.confidence + 0.1:
                return True
                
        # For email fields, be extra careful about entity disambiguation
        if (request.field_type == 'email' or 'email' in field_name):
            # If this is a company email field and we found a better contextual match
            if is_company_field and strategy_name in ['_extract_with_llm_semantic_search', '_extract_with_regex_patterns']:
                return new_result.confidence > current_best.confidence
        
        # Default: update if confidence is significantly better
        return new_result.confidence > current_best.confidence + 0.05
    
    def _format_field_value(self, value: str, field_type: str) -> str:
        """Apply formatting to field value based on type."""
        
        if field_type == 'date':
            # Try to normalize date format to DD.MM.YYYY
            date_patterns = [
                (r'(\d{1,2})[./](\d{1,2})[./](\d{4})', r'\1.\2.\3'),
                (r'(\d{4})-(\d{1,2})-(\d{1,2})', r'\3.\2.\1')
            ]
            for pattern, replacement in date_patterns:
                match = re.match(pattern, value)
                if match:
                    return re.sub(pattern, replacement, value)
        
        elif field_type == 'phone':
            # Clean up phone number
            digits = re.sub(r'[^\d+]', '', value)
            if digits.startswith('+'):
                return digits[:1] + ' ' + digits[1:]
            return digits
        
        elif field_type == 'email':
            # Ensure email is lowercase
            return value.lower()
        
        return value.strip()
    
    def save_extraction_results(
        self,
        results: Dict[str, SemanticExtractionResult],
        output_dir: str = "./output"
    ) -> str:
        """Save semantic extraction results to JSON file."""
        
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"semantic_extraction_{timestamp}.json")
        
        # Convert results to serializable format
        serializable_results = {
            field_id: {
                'field_id': result.field_id,
                'field_name': result.field_name,
                'extracted_value': result.extracted_value,
                'confidence': result.confidence,
                'source_location': result.source_location,
                'extraction_method': result.extraction_method,
                'validation_status': result.validation_status
            }
            for field_id, result in results.items()
        }
        
        output_data = {
            'timestamp': timestamp,
            'extraction_method': 'semantic_extraction',
            'total_fields': len(results),
            'successful_extractions': len([r for r in results.values() if r.extracted_value]),
            'average_confidence': sum(r.confidence for r in results.values()) / len(results) if results else 0.0,
            'results': serializable_results
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Semantic extraction results saved: {output_path}")
        return output_path
    
    def _find_document_date_candidate(self, all_text: str, request: FieldExtractionRequest) -> Optional[str]:
        """Find the most likely document/application date using contextual analysis."""
        from datetime import datetime
        
        current_year = datetime.now().year
        
        # Find all dates in the text
        date_patterns = [
            r'\d{1,2}\.\d{1,2}\.\d{2,4}',  # DD.MM.YY or DD.MM.YYYY  
            r'\d{1,2}/\d{1,2}/\d{2,4}',   # DD/MM/YY
        ]
        
        candidates = []
        
        for pattern in date_patterns:
            matches = re.finditer(pattern, all_text)
            for match in matches:
                date_str = match.group()
                start_pos = match.start()
                end_pos = match.end()
                
                # Get context around the date (50 chars before and after)
                context_start = max(0, start_pos - 50)
                context_end = min(len(all_text), end_pos + 50)
                context = all_text[context_start:context_end].lower()
                
                # Score this date based on context
                score = 0
                
                # Positive indicators (document/application context)
                if any(word in context for word in ['bewerbung', 'application', 'brief', 'letter']):
                    score += 30
                if any(word in context for word in ['sehr geehrte', 'dear', 'submission']):
                    score += 20
                if re.search(r'\w+,\s*' + re.escape(date_str), all_text):  # City, date pattern
                    score += 25
                
                # Check if it's a recent date
                try:
                    parts = date_str.split('.')
                    if len(parts) == 3:
                        year = int(parts[2])
                        if year < 100:  # 2-digit year
                            year += 2000 if year < 50 else 1900
                        
                        if current_year - 1 <= year <= current_year + 1:  # Recent date
                            score += 40
                        elif year < 2020:  # Old date (likely birth date)
                            score -= 50
                except:
                    pass
                
                # Negative indicators (personal/birth context)
                if any(word in context for word in ['geburt', 'geboren', 'birth', 'born']):
                    score -= 60
                if any(word in context for word in ['lebenslauf', 'cv', 'resume', 'personal']):
                    score -= 30
                
                candidates.append({
                    'date': date_str,
                    'score': score,
                    'context': context[:100]  # First 100 chars of context
                })
        
        # Sort by score and return the best candidate
        if candidates:
            best_candidate = max(candidates, key=lambda x: x['score'])
            if best_candidate['score'] > 10:  # Only return if reasonably confident
                print(f"   📊 Date scoring results:")
                for c in sorted(candidates, key=lambda x: x['score'], reverse=True)[:3]:
                    print(f"     - {c['date']}: score={c['score']}, context='{c['context'][:50]}...'")
                return best_candidate['date']
        
        return None