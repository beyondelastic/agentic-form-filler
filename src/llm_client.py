"""Azure OpenAI client configuration."""
from typing import Optional, List, Dict, Any
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from src.config import config

class LLMClient:
    """Azure OpenAI client wrapper."""
    
    def __init__(self):
        """Initialize the Azure OpenAI client."""
        if not config.validate():
            raise ValueError("Invalid Azure OpenAI configuration")
            
        self.client = AzureChatOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
            deployment_name=config.AZURE_OPENAI_DEPLOYMENT_NAME,
            temperature=config.MODEL_TEMPERATURE,
            max_tokens=config.MODEL_MAX_TOKENS,
        )
    
    async def invoke(self, messages: List[BaseMessage]) -> AIMessage:
        """Invoke the model with a list of messages."""
        try:
            response = await self.client.ainvoke(messages)
            return response
        except Exception as e:
            raise RuntimeError(f"Error calling Azure OpenAI: {str(e)}")
    
    def invoke_sync(self, messages: List[BaseMessage]) -> AIMessage:
        """Synchronous version of invoke."""
        try:
            response = self.client.invoke(messages)
            return response
        except Exception as e:
            raise RuntimeError(f"Error calling Azure OpenAI: {str(e)}")
    
    def create_messages(
        self, 
        system_prompt: str, 
        user_message: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> List[BaseMessage]:
        """Create a list of messages for the model."""
        messages = [SystemMessage(content=system_prompt)]
        
        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        
        # Add current user message
        messages.append(HumanMessage(content=user_message))
        
        return messages

# Global LLM client instance
llm_client = None

def get_llm_client() -> LLMClient:
    """Get or create the LLM client instance."""
    global llm_client
    if llm_client is None:
        llm_client = LLMClient()
    return llm_client
