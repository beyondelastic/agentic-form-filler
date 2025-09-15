"""Main application interface for the multi-agent form filler."""
import asyncio
import os
import json
from typing import Optional

from src.config import config
from src.models import AgentState
from src.workflow import FormFillerWorkflow

class FormFillerApp:
    """
    Main application class that provides a simple interface
    for the multi-agent form filling system.
    """
    
    def __init__(self):
        self.workflow = FormFillerWorkflow()
        self.current_state: Optional[AgentState] = None
    
    def _ensure_agent_state(self, state) -> AgentState:
        """Ensure we have a proper AgentState object."""
        if isinstance(state, AgentState):
            return state
        elif isinstance(state, dict):
            return AgentState(**state)
        else:
            # Handle LangGraph's AddableValuesDict or other formats
            try:
                state_dict = dict(state) if hasattr(state, '__iter__') else {}
                return AgentState(**state_dict)
            except Exception:
                # Fallback to empty state
                return AgentState()
    
    async def start(self):
        """Start a new form filling session."""
        print("🚀 Starting Multi-Agent Form Filler")
        print("=" * 50)
        
        # Validate configuration
        if not config.validate():
            print("\n❌ Please set up your Azure OpenAI configuration first.")
            print("1. Copy .env.example to .env")
            print("2. Fill in your Azure OpenAI credentials")
            return
        
        # Show available extraction methods
        self._show_extraction_capabilities()
        
        # Initialize state and workflow
        initial_state = AgentState()
        self.current_state = initial_state
        
        # Compile workflow
        self.workflow.compile()
        
        # Start the workflow
        workflow_result = await self.workflow.run(initial_state)
        self.current_state = self._ensure_agent_state(workflow_result)
        
        # Enter interactive loop
        await self._interactive_loop()
    
    def _show_extraction_capabilities(self):
        """Display available extraction methods."""
        print("\n🔧 Available Extraction Methods:")
        
        if config.has_document_intelligence():
            print("✅ Azure Document Intelligence - High accuracy key-value extraction")
        else:
            print("⚠️  Azure Document Intelligence - Not configured (optional)")
            print("   Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY for enhanced extraction")
        
        print("✅ Text Extraction + LLM - Fallback method using PDF text parsing")
        print()
    
    async def _interactive_loop(self):
        """Interactive loop for human-in-the-loop processing."""
        
        while True:
            # Check if we need human input
            if self.current_state and self.current_state.requires_human_review:
                
                # Display current conversation
                self._display_conversation()
                
                # Get user input with EOF handling
                try:
                    user_input = input("\n👤 Your input (or 'quit' to exit): ").strip()
                except EOFError:
                    print("\n👋 Input stream ended. Goodbye!")
                    break
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                # Process feedback and continue workflow
                self.current_state = self.workflow.process_human_feedback(
                    self.current_state, user_input
                )
                
                # Continue the workflow  
                workflow_result = await self.workflow.run(self.current_state)
                self.current_state = self._ensure_agent_state(workflow_result)
                
            elif self.current_state and self.current_state.current_step == "completed":
                # Workflow completed
                self._display_conversation()
                
                # Ask if user wants to continue
                try:
                    continue_input = input("\n🔄 Start a new session? (yes/no): ").strip().lower()
                    if continue_input in ['yes', 'y']:
                        # Reset and start new session
                        initial_state = AgentState()
                        workflow_result = await self.workflow.run(initial_state)
                        self.current_state = self._ensure_agent_state(workflow_result)
                    else:
                        print("👋 Goodbye!")
                        break
                except EOFError:
                    print("\n👋 Input stream ended. Goodbye!")
                    break
            else:
                # Something went wrong
                print("❓ Workflow ended unexpectedly.")
                break
    
    def _display_conversation(self):
        """Display the conversation history."""
        
        print("\n" + "=" * 60)
        print("CONVERSATION HISTORY")
        print("=" * 60)
        
        if not self.current_state or not self.current_state.messages:
            print("No messages yet.")
            return
        
        for i, message in enumerate(self.current_state.messages):
            role = message.get("role", "unknown")
            agent = message.get("agent", "unknown")
            content = message.get("content", "")
            
            # Format based on role
            if role == "user":
                print(f"\n👤 USER:")
            elif role == "assistant":
                if agent == "orchestrator":
                    print(f"\n🎯 ORCHESTRATOR:")
                elif agent == "data_extractor":
                    print(f"\n📄 DATA EXTRACTOR:")
                elif agent == "form_filler":
                    print(f"\n📝 FORM FILLER:")
                else:
                    print(f"\n🤖 {agent.upper()}:")
            
            # Print content with proper wrapping
            if content:
                print(self._wrap_text(content, 58))
        
        print("\n" + "=" * 60)
    
    def _wrap_text(self, text: str, width: int) -> str:
        """Wrap text to specified width."""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if len(current_line + word) <= width:
                current_line += word + " "
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        
        if current_line:
            lines.append(current_line.strip())
        
        return "\n".join(lines)
    
    def load_sample_data(self):
        """Load sample PDF for testing."""
        data_dir = "data"
        if os.path.exists(data_dir):
            pdf_files = [f for f in os.listdir(data_dir) if f.endswith('.pdf')]
            if pdf_files:
                sample_pdf = os.path.join(data_dir, pdf_files[0])
                if self.current_state:
                    self.current_state.pdf_file_path = sample_pdf
                    print(f"📄 Loaded sample PDF: {sample_pdf}")
                    return sample_pdf
        
        print("❌ No sample PDF files found in data/ directory")
        return None

async def main():
    """Main entry point."""
    app = FormFillerApp()
    await app.start()

def main_sync():
    """Synchronous entry point."""
    asyncio.run(main())

if __name__ == "__main__":
    main_sync()