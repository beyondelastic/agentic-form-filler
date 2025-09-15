"""Azure Document Intelligence tool for extracting key-value pairs from PDFs.

Uses Azure Document Intelligence (formerly Form Recognizer) prebuilt-document
model to extract structured data from PDF files without requiring custom models.
"""

import os
import glob
from typing import List, Dict, Any, Optional

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from src.config import config

class AzureDocumentIntelligenceTool:
    """Tool for extracting key-value pairs using Azure Document Intelligence."""
    
    def __init__(self):
        """Initialize the Azure Document Intelligence client."""
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the DocumentAnalysisClient if credentials are available."""
        try:
            if config.has_document_intelligence():
                endpoint, key = config.get_azure_doc_intelligence_credentials()
                self.client = DocumentAnalysisClient(
                    endpoint=endpoint, 
                    credential=AzureKeyCredential(key)
                )
                print("✅ Azure Document Intelligence client initialized")
            else:
                print("⚠️ Azure Document Intelligence not configured - will fallback to basic extraction")
        except Exception as e:
            print(f"⚠️ Failed to initialize Azure Document Intelligence: {str(e)}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Azure Document Intelligence is available."""
        return self.client is not None
    
    def extract_from_file(
        self,
        file_path: str,
        include_tables: bool = True,
        include_cell_content: bool = False,
        model_id: str = "prebuilt-document"
    ) -> Dict[str, Any]:
        """
        Extract key-value pairs and tables from a single PDF file.
        
        Args:
            file_path: Path to the PDF file
            include_tables: Whether to extract table data
            include_cell_content: Whether to include cell content in tables
            model_id: Azure model to use (default: prebuilt-document)
        
        Returns:
            Dictionary with extracted data, confidence scores, and metadata
        """
        
        if not self.client:
            raise ValueError("Azure Document Intelligence client not initialized")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            print(f"📊 Analyzing document with Azure Document Intelligence: {file_path}")
            
            with open(file_path, "rb") as f:
                poller = self.client.begin_analyze_document(model_id, f)
                doc_result = poller.result()
            
            # Extract key-value pairs from document fields
            kv_pairs: Dict[str, str] = {}
            kv_confidence: Dict[str, float] = {}
            
            # Process document-level fields
            for doc in doc_result.documents or []:
                for field_name, field in (doc.fields or {}).items():
                    normalized_key = self._normalize_field_name(field_name)
                    if field and field.value is not None:
                        kv_pairs[normalized_key] = str(field.value)
                        if field.confidence is not None:
                            kv_confidence[normalized_key] = float(field.confidence)
            
            # Process general key-value pairs
            for kv in getattr(doc_result, "key_value_pairs", []) or []:
                try:
                    key_text = (kv.key.content if kv.key else "").strip()
                    value_text = (kv.value.content if kv.value else "").strip()
                    
                    if key_text and value_text:
                        normalized_key = self._normalize_field_name(key_text)
                        if normalized_key not in kv_pairs:  # Don't overwrite document fields
                            kv_pairs[normalized_key] = value_text
                            if kv.confidence is not None:
                                kv_confidence[normalized_key] = float(kv.confidence)
                except Exception:
                    continue
            
            # Extract tables if requested
            tables_data = []
            if include_tables:
                tables_data = self._extract_tables(doc_result.tables or [], include_cell_content)
            
            result = {
                "file_name": os.path.basename(file_path),
                "model_version": getattr(doc_result, "model_version", None),
                "extraction_method": "azure_document_intelligence",
                "key_values": kv_pairs,
                "kv_confidence": kv_confidence,
                "table_count": len(tables_data),
                "tables": tables_data,
                "total_fields": len(kv_pairs),
                "average_confidence": sum(kv_confidence.values()) / len(kv_confidence) if kv_confidence else 0.0
            }
            
            print(f"✅ Extracted {len(kv_pairs)} key-value pairs with avg confidence {result['average_confidence']:.2%}")
            return result
            
        except Exception as e:
            print(f"❌ Error analyzing document: {str(e)}")
            raise
    
    def extract_from_pattern(
        self,
        pattern: Optional[str] = None,
        include_tables: bool = True,
        include_cell_content: bool = False,
        model_id: str = "prebuilt-document"
    ) -> Dict[str, Any]:
        """
        Extract key-value pairs from multiple files matching a pattern.
        
        Args:
            pattern: Glob pattern for files (default: data/*.pdf)
            include_tables: Whether to extract table data
            include_cell_content: Whether to include cell content in tables
            model_id: Azure model to use
        
        Returns:
            Dictionary with results from all processed documents
        """
        
        if not self.client:
            raise ValueError("Azure Document Intelligence client not initialized")
        
        # Determine file pattern
        file_pattern = pattern or config.DOCUMENT_PATH
        file_paths = sorted(glob.glob(file_pattern))
        
        # Try fallback patterns if no files found
        if not file_paths:
            fallback_patterns = ['./data/*.pdf', 'data/*.pdf', '*.pdf']
            for fallback in fallback_patterns:
                file_paths = sorted(glob.glob(fallback))
                if file_paths:
                    file_pattern = fallback
                    break
        
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        warnings: List[str] = []
        
        if not file_paths:
            warnings.append(f"No PDF files found matching pattern: {file_pattern}")
            return {
                "pattern": file_pattern,
                "documents": [],
                "errors": [],
                "warnings": warnings,
                "summary": {"total_files": 0, "successful": 0, "failed": 0}
            }
        
        print(f"📂 Processing {len(file_paths)} files with pattern: {file_pattern}")
        
        # Process each file
        for file_path in file_paths:
            try:
                result = self.extract_from_file(
                    file_path, include_tables, include_cell_content, model_id
                )
                results.append(result)
            except Exception as e:
                error_msg = f"Failed to process {file_path}: {str(e)}"
                print(f"❌ {error_msg}")
                errors.append({
                    "file": file_path,
                    "error": str(e)
                })
        
        # Generate summary
        successful = len(results)
        failed = len(errors)
        total_fields = sum(r.get("total_fields", 0) for r in results)
        avg_confidence = sum(r.get("average_confidence", 0) for r in results) / successful if successful > 0 else 0.0
        
        # Check for warnings
        if not errors and all(r.get("table_count", 0) == 0 for r in results) and include_tables:
            warnings.append("No tables detected in any document")
        
        return {
            "pattern": file_pattern,
            "documents": results,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "total_files": len(file_paths),
                "successful": successful,
                "failed": failed,
                "total_fields_extracted": total_fields,
                "average_confidence": avg_confidence
            }
        }
    
    def _normalize_field_name(self, field_name: str) -> str:
        """Normalize field names to consistent format."""
        return field_name.strip().lower().replace(" ", "_").replace("-", "_")
    
    def _extract_tables(self, tables: List[Any], include_cell_content: bool) -> List[Dict[str, Any]]:
        """Extract table data from document analysis result."""
        tables_data = []
        
        for table_idx, table in enumerate(tables):
            cells = []
            for cell in table.cells:
                cell_entry = {
                    "row": cell.row_index,
                    "col": cell.column_index,
                    "row_span": cell.row_span or 1,
                    "col_span": cell.column_span or 1,
                }
                
                if include_cell_content:
                    cell_entry["content"] = cell.content or ""
                
                cells.append(cell_entry)
            
            table_data = {
                "index": table_idx,
                "row_count": table.row_count,
                "column_count": table.column_count,
                "cells": cells,
            }
            
            tables_data.append(table_data)
        
        return tables_data
