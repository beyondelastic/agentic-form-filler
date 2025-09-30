"""Data models for the multi-agent form filler application."""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from enum import Enum

class AgentType(str, Enum):
    """Types of agents in the system."""
    ORCHESTRATOR = "orchestrator"
    FORM_LEARNER = "form_learner"
    DATA_EXTRACTOR = "data_extractor"
    FORM_FILLER = "form_filler"
    QUALITY_CHECKER = "quality_checker"

class MessageType(str, Enum):
    """Types of messages between agents."""
    USER_INPUT = "user_input"
    TASK_ASSIGNMENT = "task_assignment"
    DATA_EXTRACTION_REQUEST = "data_extraction_request"
    DATA_EXTRACTION_RESPONSE = "data_extraction_response"
    FORM_FILL_REQUEST = "form_fill_request"
    FORM_FILL_RESPONSE = "form_fill_response"
    HUMAN_FEEDBACK = "human_feedback"
    COMPLETION = "completion"

class AgentState(BaseModel):
    """State shared between agents."""
    # Conversation management
    messages: List[Dict[str, Any]] = []
    current_step: str = "initialization"
    
    # User inputs and requirements
    user_instructions: Optional[str] = None
    pdf_file_path: Optional[str] = None  # For backward compatibility
    pdf_file_paths: Optional[List[str]] = None  # Support multiple input files
    form_template_path: Optional[str] = None
    
    # Data extraction results
    extracted_data: Optional[Dict[str, Any]] = None
    extraction_confidence: Optional[float] = None
    
    # Form analysis results
    form_fields: Optional[Dict[str, Any]] = None
    field_types: Optional[Dict[str, str]] = None
    required_fields: Optional[List[str]] = None
    form_analysis_confidence: Optional[float] = None
    
    # Form learning results (new comprehensive structure)
    form_structure: Optional[Dict[str, Any]] = None
    form_learning_summary: Optional[Dict[str, Any]] = None
    
    # Form filling results
    filled_form_path: Optional[str] = None
    form_filling_status: Optional[str] = None
    
    # Human feedback and iteration
    requires_human_review: bool = False
    human_feedback: Optional[str] = None
    iteration_count: int = 0
    max_iterations: int = 3
    
    # Missing fields handling
    missing_fields_to_fill: Optional[List[str]] = None
    
    # Quality checking results
    quality_assessment: Optional['QualityAssessmentResult'] = None
    reference_form_path: Optional[str] = None
    reference_patterns: Optional[Dict[str, 'ReferenceFieldPattern']] = None
    quality_iteration_count: int = 0
    max_quality_iterations: int = 2
    field_corrections: Optional[Dict[str, Any]] = None
    
    # Agent tracking
    current_agent: Optional[AgentType] = None
    completed_agents: List[AgentType] = []
    
class Message(BaseModel):
    """Message structure for agent communication."""
    type: MessageType
    sender: AgentType
    recipient: Optional[AgentType] = None
    content: str
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    
class ExtractionResult(BaseModel):
    """Result from data extraction."""
    extracted_fields: Dict[str, Any]
    confidence_score: float
    source_file: str
    extraction_method: str
    errors: Optional[List[str]] = None

class FormAnalysisResult(BaseModel):
    """Result from form field analysis."""
    form_fields: Dict[str, Any]
    field_types: Dict[str, str]
    required_fields: List[str]
    confidence_score: float
    source_file: str
    analysis_method: str
    errors: Optional[List[str]] = None
    
class FormFillingResult(BaseModel):
    """Result from form filling."""
    output_file_path: str
    filled_fields: Dict[str, Any]
    success: bool
    errors: Optional[List[str]] = None

class QualityIssue(BaseModel):
    """Represents a quality issue found during form validation."""
    field_id: str
    field_name: str
    issue_type: str  # "semantic_mismatch", "data_type_error", "contextual_error", etc.
    current_value: Any
    expected_pattern: Optional[str] = None
    confidence: float
    suggestion: str
    severity: str  # "low", "medium", "high", "critical"

class ReferenceFieldPattern(BaseModel):
    """Pattern learned from reference forms for a specific field."""
    field_id: str
    field_name: str
    field_type: str
    semantic_category: str  # "personal_date", "document_date", "name", "contact", etc.
    value_pattern: Optional[str] = None  # regex or description
    context_clues: List[str] = []
    example_values: List[str] = []

class QualityAssessmentResult(BaseModel):
    """Result from quality assessment."""
    overall_quality_score: float
    issues_found: List[QualityIssue]
    passed_checks: int
    total_checks: int
    reference_form_used: Optional[str] = None
    assessment_timestamp: str
    requires_correction: bool
