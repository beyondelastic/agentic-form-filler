"""Configuration for the multi-agent form filler application."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration."""
    
    # Azure OpenAI Configuration
    AZURE_OPENAI_API_KEY: Optional[str] = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT: Optional[str] = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    AZURE_OPENAI_DEPLOYMENT_NAME: Optional[str] = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    
    # Azure Document Intelligence Configuration
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: Optional[str] = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    AZURE_DOCUMENT_INTELLIGENCE_KEY: Optional[str] = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    
    # Model Configuration
    MODEL_TEMPERATURE: float = 0.1
    MODEL_MAX_TOKENS: int = 4000
    
    # File paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root directory
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    FORM_DIR: str = os.getenv("FORM_DIR", "form")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")
    SAMPLE_DIR: str = os.getenv("SAMPLE_DIR", "sample")
    DOCUMENT_PATH: str = os.getenv("DOCUMENT_PATH", f"{os.getenv('DATA_DIR', 'data')}/*.pdf")
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that required configuration is present."""
        required_fields = [
            cls.AZURE_OPENAI_API_KEY,
            cls.AZURE_OPENAI_ENDPOINT,
            cls.AZURE_OPENAI_DEPLOYMENT_NAME
        ]
        
        missing_fields = [field for field in required_fields if not field]
        
        if missing_fields:
            print("Missing required environment variables:")
            print("- AZURE_OPENAI_API_KEY")
            print("- AZURE_OPENAI_ENDPOINT") 
            print("- AZURE_OPENAI_DEPLOYMENT_NAME")
            return False
            
        return True
    
    @classmethod
    def get_azure_doc_intelligence_credentials(cls) -> tuple[str, str]:
        """Get Azure Document Intelligence credentials."""
        endpoint = cls.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        key = cls.AZURE_DOCUMENT_INTELLIGENCE_KEY
        
        if not endpoint or not key:
            raise ValueError(
                "Azure Document Intelligence credentials missing. "
                "Please set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY"
            )
        
        return endpoint, key
    
    @classmethod
    def has_document_intelligence(cls) -> bool:
        """Check if Document Intelligence is configured."""
        return bool(cls.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and cls.AZURE_DOCUMENT_INTELLIGENCE_KEY)
    
    @classmethod
    def get_data_dir_path(cls) -> str:
        """Get full path to data directory."""
        return os.path.join(cls.BASE_DIR, cls.DATA_DIR)
    
    @classmethod
    def get_form_dir_path(cls) -> str:
        """Get full path to form directory."""
        return os.path.join(cls.BASE_DIR, cls.FORM_DIR)
    
    @classmethod
    def get_output_dir_path(cls) -> str:
        """Get full path to output directory."""
        return os.path.join(cls.BASE_DIR, cls.OUTPUT_DIR)
    
    @classmethod
    def get_sample_dir_path(cls) -> str:
        """Get full path to sample directory."""
        return os.path.join(cls.BASE_DIR, cls.SAMPLE_DIR)

# Global config instance
config = Config()