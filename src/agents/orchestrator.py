"""Orchestrator agent that manages the conversation and coordinates other agents."""
import os
from typing import Dict, Any, Optional, List
from src.models import AgentState, AgentType, MessageType, Message, QualityIssue
from src.llm_client import get_llm_client
from src.config import config

class OrchestratorAgent:
    """
    Orchestrator agent that:
    1. Starts conversations and gathers user requirements
    2. Coordinates between data extractor and form filler agents
    3. Manages human-in-the-loop interactions
    4. Handles feedback and iterations
    """
    
    def __init__(self):
        self.agent_type = AgentType.ORCHESTRATOR
        self.llm_client = get_llm_client()
    
    async def process(self, state: AgentState) -> AgentState:
        """Process the current state and determine next actions."""
        print(f"\n🎯 Orchestrator Agent Processing - Current Step: {state.current_step}")
        print(f"   Agent: {state.current_agent}, Human Review: {state.requires_human_review}")
        
        # Route based on current step
        if state.current_step == "initialization":
            return await self._initialize_conversation(state)
        elif state.current_step == "gathering_requirements":
            return await self._gather_requirements(state)
        elif state.current_step == "coordinating_extraction":
            return await self._coordinate_extraction(state)
        elif state.current_step == "form_learning":
            return await self._handle_form_learning_complete(state)
        elif state.current_step == "reviewing_extraction":
            return await self._review_extraction(state)
        elif state.current_step == "handling_missing_fields":
            return await self._handle_missing_fields(state)
        elif state.current_step == "awaiting_missing_fields_input":
            # This step requires human input - just return the state as-is
            # The actual processing happens in process_human_feedback
            state.requires_human_review = True
            return state
        elif state.current_step == "coordinating_form_fill":
            return await self._coordinate_form_fill(state)
        elif state.current_step == "final_review":
            return await self._final_review(state)
        elif state.current_step == "quality_correction":
            return await self._handle_quality_correction(state)
        elif state.current_step == "completed":
            return await self._handle_completion(state)
        elif state.current_step == "finished":
            return await self._handle_finished(state)
        else:
            return await self._handle_unknown_step(state)
    
    async def _initialize_conversation(self, state: AgentState) -> AgentState:
        """Initialize the conversation with the user."""
        
        # Check for available files first
        data_files = self._check_data_files()
        form_files = self._check_form_files()
        
        if not data_files and not form_files:
            welcome_message = """🤖 **Form Filler Assistant** - Orchestrator Agent

Welcome! I'll help you extract data from PDF documents and fill forms automatically.

❌ **No files found!**

Please add your files to the following directories:
  - **{config.DATA_DIR}/**: Place your PDF documents to extract data from
  - **{config.FORM_DIR}/**: Place your PDF form templates to be filled

Once you've added your files, type 'check files' to continue."""
        elif not data_files:
            welcome_message = f"""🤖 **Form Filler Assistant** - Orchestrator Agent

Welcome! I found form templates but no data documents.

✅ **Found form templates:**
{self._format_file_list(form_files)}

❌ **No data documents found!**

Please add PDF documents to the **{config.DATA_DIR}/** directory, then type 'check files' to continue."""
        elif not form_files:
            welcome_message = f"""🤖 **Form Filler Assistant** - Orchestrator Agent

Welcome! I found data documents but no form templates.

✅ **Found data documents:**  
{self._format_file_list(data_files)}

❌ **No form templates found!**

Please add form templates (PDF or Excel .xlsm/.xlsx) to the **{config.FORM_DIR}/** directory, then type 'check files' to continue."""
        else:
            # Both files available - proceed
            welcome_message = f"""🤖 **Form Filler Assistant** - Orchestrator Agent

Welcome! I found files in both directories:

✅ **Data documents:** 
{self._format_file_list(data_files)}

✅ **Form templates:**
{self._format_file_list(form_files)}

Great! Now tell me:

1. **What type of data** should I extract? (e.g., patient info, invoice details, contract terms)

2. **Any specific mapping instructions** for filling the form?

3. **Which specific files** should I use? (or I can use the first available ones)"""
            # Set all available files for processing
            state.pdf_file_paths = data_files if data_files else []
            state.pdf_file_path = data_files[0] if data_files else None  # Backward compatibility
            state.form_template_path = form_files[0] if form_files else None
        
        # Add welcome message to conversation
        state.messages.append({
            "role": "assistant",
            "content": welcome_message,
            "agent": self.agent_type.value
        })
        
        state.current_step = "gathering_requirements"
        state.current_agent = self.agent_type
        state.requires_human_review = True  # Wait for user input
        
        return state
    
    async def _gather_requirements(self, state: AgentState) -> AgentState:
        """Process user requirements and validate inputs."""
        if not state.user_instructions:
            # Still waiting for user input
            return state
        
        # Handle special commands
        user_input = state.user_instructions.lower().strip()
        
        if user_input == "check files":
            # Re-check files and update state
            return await self._initialize_conversation(state)
        
        # Check if we have the required files
        data_files = self._check_data_files()
        form_files = self._check_form_files()
        
        if not data_files or not form_files:
            # Still missing files
            missing_msg = "❌ Still missing files:\n"
            if not data_files:
                missing_msg += f"- Add PDF documents to **{config.DATA_DIR}/** directory\n"
            if not form_files:
                missing_msg += f"- Add form templates (PDF or Excel .xlsm/.xlsx) to **{config.FORM_DIR}/** directory\n"
            missing_msg += "\nType 'check files' when ready to continue."
            
            state.messages.append({
                "role": "user",
                "content": state.user_instructions,
                "agent": "user"
            })
            state.messages.append({
                "role": "assistant",
                "content": missing_msg,
                "agent": self.agent_type.value
            })
            
            state.requires_human_review = True
            return state
        
        # Files are available, set them if not already set
        if not state.pdf_file_paths:
            state.pdf_file_paths = data_files
        if not state.pdf_file_path:
            state.pdf_file_path = data_files[0]  # Backward compatibility
        if not state.form_template_path:
            state.form_template_path = form_files[0]
        
        # Auto-detect reference form in sample directory
        if not state.reference_form_path:
            state.reference_form_path = self._detect_reference_form(state.form_template_path)
        
        # Process requirements with LLM
        system_prompt = """You are an orchestrator agent in a multi-agent form-filling system.

The user has provided instructions for data extraction and form filling. Analyze their requirements and determine if we can proceed.

Respond in this format:
ANALYSIS: [Your analysis of the requirements]
DATA_REQUIREMENTS: [What data should be extracted]
READY_TO_PROCEED: [YES/NO - whether we can start extraction]
NEXT_ACTION: [What should happen next]
"""

        user_message = f"User instructions: {state.user_instructions}"
        
        messages = self.llm_client.create_messages(system_prompt, user_message)
        response = await self.llm_client.invoke(messages)
        
        # Add to conversation history
        state.messages.append({
            "role": "user", 
            "content": state.user_instructions,
            "agent": "user"
        })
        
        response_content = f"""✅ **Files ready for processing:**

**Data document:** {os.path.basename(state.pdf_file_path)}
**Form template:** {os.path.basename(state.form_template_path)}

**Analysis:**
{response.content}

Proceeding to data extraction..."""
        
        state.messages.append({
            "role": "assistant",
            "content": response_content,
            "agent": self.agent_type.value
        })
        
        # Always proceed if we have both files - coordinate extraction immediately
        print("✅ Requirements gathered successfully. Moving to data extraction.")
        
        # Directly coordinate extraction instead of requiring another workflow cycle
        return await self._coordinate_extraction(state)
    
    async def _coordinate_extraction(self, state: AgentState) -> AgentState:
        """Coordinate extraction workflow - first form learning, then data extraction."""
        print("📚 Starting form analysis and data extraction workflow...")
        
        # Check if form learning has been completed
        form_learning_complete = any(
            msg.get("type") == "form_learning_complete" 
            for msg in state.messages
        )
        
        if not form_learning_complete:
            # First step: Form learning
            print("📊 Step 1: Form structure analysis...")
            
            state.messages.append({
                "role": "assistant", 
                "content": f"🔍 **Step 1: Analyzing form structure**\n\n� Form: {os.path.basename(state.form_template_path)}\n\nAnalyzing sections, fields, and requirements to optimize data extraction...",
                "agent": self.agent_type.value
            })
            
            print(f"✅ Routing to FORM_LEARNER agent")
            state.current_step = "form_learning"
            state.current_agent = AgentType.FORM_LEARNER
            state.requires_human_review = False
            
            return state
        else:
            # Form learning completed, proceed to data extraction
            print("📄 Step 2: Data extraction with form insights...")
            
            # Create task for data extractor
            extraction_task = Message(
                type=MessageType.DATA_EXTRACTION_REQUEST,
                sender=self.agent_type,
                recipient=AgentType.DATA_EXTRACTOR,
                content="Extract data from the provided document using form structure insights",
                data={
                    "pdf_path": state.pdf_file_path,
                    "requirements": state.user_instructions
                }
            )
            
            # Create document list message
            doc_list = [os.path.basename(f) for f in (state.pdf_file_paths or [state.pdf_file_path] if state.pdf_file_path else [])]
            doc_message = f"{len(doc_list)} documents: {', '.join(doc_list)}" if len(doc_list) > 1 else doc_list[0] if doc_list else "None"
            
            state.messages.append({
                "role": "assistant",
                "content": f"🔄 **Step 2: Extracting data with form insights**\n\n📄 Documents: {doc_message}\n📋 Template: {os.path.basename(state.form_template_path)}\n\nUsing form structure analysis for intelligent data extraction...",
                "agent": self.agent_type.value,
                "task": extraction_task.dict()
            })
            
            print(f"✅ Routing to DATA_EXTRACTOR agent")
            state.current_step = "data_extraction"  # Hand off to data extractor
            state.current_agent = AgentType.DATA_EXTRACTOR
            state.requires_human_review = False  # Let workflow continue to data extractor
            
            return state
    
    async def _handle_form_learning_complete(self, state: AgentState) -> AgentState:
        """Handle completion of form learning and proceed to data extraction."""
        print("✅ Form learning completed, proceeding to data extraction...")
        
        # Check if form learning was successful
        form_learning_data = next(
            (msg.get("data") for msg in state.messages if msg.get("type") == "form_learning_complete"), 
            None
        )
        
        if form_learning_data:
            form_structure = form_learning_data.get("form_structure", {})
            sections_count = len(form_structure.get("sections", []))
            fields_count = form_structure.get("total_fields", 0)
            
            state.messages.append({
                "role": "assistant",
                "content": f"✅ **Form analysis complete!**\n\n📊 **Analysis Results:**\n- **Form:** {form_structure.get('title', 'Unknown')}\n- **Sections:** {sections_count}\n- **Fields:** {fields_count}\n\nNow proceeding to intelligent data extraction...",
                "agent": self.agent_type.value
            })
        else:
            state.messages.append({
                "role": "assistant", 
                "content": "⚠️ Form learning completed with limited results. Proceeding to basic data extraction...",
                "agent": self.agent_type.value
            })
        
        # Continue to data extraction
        return await self._coordinate_extraction(state)
    
    async def _review_extraction(self, state: AgentState) -> AgentState:
        """Review extraction results and decide next steps."""
        print("🔍 Reviewing extraction results...")
        
        if not state.extracted_data:
            state.messages.append({
                "role": "assistant",
                "content": "❌ No data was extracted. Please check the document and try again.",
                "agent": self.agent_type.value
            })
            state.requires_human_review = True
            return state
        
        # Present results to user for review
        review_message = f"""
📊 **Data Extraction Complete**

Extracted data:
{state.extracted_data}

Confidence: {state.extraction_confidence or 'N/A'}

Please review this data:
- Type 'approve' to proceed with form filling
- Type 'retry' to extract data again  
- Provide feedback for improvements
"""
        
        state.messages.append({
            "role": "assistant", 
            "content": review_message,
            "agent": self.agent_type.value
        })
        
        state.requires_human_review = True
        state.current_step = "awaiting_extraction_review"
        
        return state
    
    async def _handle_missing_fields(self, state: AgentState) -> AgentState:
        """Handle missing form fields - allow user to fill them or skip."""
        print("📝 Checking for missing form fields...")
        
        # Identify missing fields by comparing form fields with extracted data
        missing_fields = []
        if state.form_fields and state.required_fields:
            for field_name in state.required_fields:
                # Check if we have data for this field (case-insensitive)
                found = False
                field_lower = field_name.lower()
                
                for data_key in (state.extracted_data or {}).keys():
                    data_key_lower = data_key.lower()
                    if (field_lower == data_key_lower or 
                        field_lower in data_key_lower or 
                        data_key_lower in field_lower or
                        self._is_similar_field_name(field_lower, data_key_lower)):
                        found = True
                        break
                
                if not found:
                    missing_fields.append(field_name)
        
        # Prepare user interaction message (always allow user to add more fields or proceed)
        if not missing_fields:
            print("✅ All required fields have data")
            missing_fields_message = f"""
📝 **Data Extraction Complete**

All required fields have been extracted successfully! You can now:

**Options:**
1. **Add additional fields**: Type field values (e.g., "notes=Additional information")  
2. **Proceed with form filling**: Type "print" to fill the form with current data
3. **Retry extraction**: Type "retry" to extract data again with different instructions

**To add a field**: Type `field_name=value` (e.g., `notes=Additional notes`)
**To add multiple**: Separate with commas (e.g., `notes=Extra info, category=Important`)
"""
        else:
            missing_fields_message = f"""
📝 **Missing Form Fields Detected**

The following required form fields don't have corresponding data:

{self._format_missing_fields_list(missing_fields)}

**Options:**
1. **Fill missing fields**: Type field values one by one (e.g., "patient_name=John Smith")
2. **Skip and proceed**: Type "print" to fill the form with available data only
3. **Retry extraction**: Type "retry" to extract data again with better instructions

**To fill a field**: Type `field_name=value` (e.g., `patient_name=John Smith`)
**To fill multiple**: Separate with commas (e.g., `patient_name=John Smith, doctor_name=Dr. Johnson`)
"""
        
        state.messages.append({
            "role": "assistant",
            "content": missing_fields_message,
            "agent": self.agent_type.value
        })
        
        state.requires_human_review = True
        state.current_step = "awaiting_missing_fields_input"
        
        # Store missing fields for processing
        if not hasattr(state, 'missing_fields_to_fill'):
            state.missing_fields_to_fill = missing_fields
        
        return state
    
    def _is_similar_field_name(self, field1: str, field2: str) -> bool:
        """Check if two field names are similar (helper for missing field detection)."""
        # Remove common separators
        clean1 = field1.replace('_', '').replace('-', '').replace(' ', '').replace(':', '')
        clean2 = field2.replace('_', '').replace('-', '').replace(' ', '').replace(':', '')
        
        # Check for common patterns
        patterns = {
            'name': ['patient', 'full', 'first', 'last'],
            'date': ['birth', 'dob', 'born'],
            'phone': ['telephone', 'mobile', 'contact', 'tel'],
            'email': ['mail', 'e_mail'],
            'id': ['identifier', 'number', 'num'],
            'doctor': ['physician', 'dr', 'md'],
            'diagnosis': ['condition', 'disease', 'disorder']
        }
        
        for base, aliases in patterns.items():
            if base in clean1 and any(alias in clean2 for alias in aliases):
                return True
            if base in clean2 and any(alias in clean1 for alias in aliases):
                return True
        
        return clean1 in clean2 or clean2 in clean1
    
    def _format_missing_fields_list(self, missing_fields: list) -> str:
        """Format missing fields list for display."""
        if not missing_fields:
            return "  (none)"
        
        formatted = []
        for field in missing_fields:
            display_name = field.replace('_', ' ').title()
            formatted.append(f"  - {display_name} (`{field}`)")
        
        return "\n".join(formatted)
    
    async def _coordinate_form_fill(self, state: AgentState) -> AgentState:
        """Coordinate with the form filler agent."""
        print("📝 Coordinating form filling...")
        
        form_fill_task = Message(
            type=MessageType.FORM_FILL_REQUEST,
            sender=self.agent_type,
            recipient=AgentType.FORM_FILLER,
            content="Fill the form with extracted data",
            data={
                "extracted_data": state.extracted_data,
                "form_path": state.form_template_path,
                "requirements": state.user_instructions
            }
        )
        
        state.messages.append({
            "role": "assistant",
            "content": "🔄 Assigning form filling task to Form Filler Agent...",
            "agent": self.agent_type.value,
            "task": form_fill_task.dict()
        })
        
        state.current_step = "form_filling"  # Hand off to form filler
        state.current_agent = AgentType.FORM_FILLER
        state.requires_human_review = False  # Let workflow continue to form filler
        
        print(f"✅ Routing to FORM_FILLER agent")
        
        return state
    
    async def _final_review(self, state: AgentState) -> AgentState:
        """Present final results to user."""
        print("🏁 Final review...")
        
        final_message = f"""
✅ **Process Complete!**

**Summary:**
- Document processed: {state.pdf_file_path or 'N/A'}
- Data extracted: {len(state.extracted_data or {}) } fields
- Form filled: {state.filled_form_path or 'N/A'}
- Status: {state.form_filling_status or 'N/A'}

The form has been successfully filled with the extracted data.

Would you like to:
1. Process another document
2. Make corrections  
3. Exit
"""
        
        state.messages.append({
            "role": "assistant",
            "content": final_message, 
            "agent": self.agent_type.value
        })
        
        state.current_step = "completed"
        state.requires_human_review = True
        
        return state
    
    async def _handle_completion(self, state: AgentState) -> AgentState:
        """Handle workflow completion - wait for user decision on next action."""
        print("\n🎉 Workflow Completed - Awaiting user decision...")
        
        # The completion message was already added in _final_review
        # Just ensure we're waiting for human input
        state.requires_human_review = True
        
        return state
    
    async def _handle_finished(self, state: AgentState) -> AgentState:
        """Handle workflow finish - no further processing needed."""
        print("\n✅ Workflow finished - Session ended")
        
        # No further processing required
        state.requires_human_review = False
        
        return state
    
    async def _handle_unknown_step(self, state: AgentState) -> AgentState:
        """Handle unexpected states."""
        error_message = f"❓ Unknown step: {state.current_step}. Returning to initialization."
        
        state.messages.append({
            "role": "assistant",
            "content": error_message,
            "agent": self.agent_type.value
        })
        
        state.current_step = "initialization"
        return state
    
    def handle_human_feedback(self, state: AgentState, feedback: str) -> AgentState:
        """Process human feedback and update state accordingly."""
        state.human_feedback = feedback
        state.requires_human_review = False
        
        # Route based on current step and feedback
        if state.current_step == "gathering_requirements":
            state.user_instructions = feedback
        elif state.current_step == "awaiting_extraction_review":
            if feedback.lower() == "approve":
                state.current_step = "handling_missing_fields"
            elif feedback.lower() == "retry":
                state.current_step = "coordinating_extraction"
                state.extracted_data = None
            else:
                # Feedback for improvement
                state.current_step = "coordinating_extraction"
                state.user_instructions += f"\nAdditional feedback: {feedback}"
        elif state.current_step == "awaiting_missing_fields_input":
            self._process_missing_fields_input(state, feedback)
        elif state.current_step == "completed":
            self._handle_completion_feedback(state, feedback)
        
        return state
    
    def _process_missing_fields_input(self, state: AgentState, feedback: str) -> None:
        """Process user input for missing fields."""
        feedback_lower = feedback.lower().strip()
        
        if feedback_lower in ["print", "approve", "proceed", "continue", "skip"]:
            # Proceed with form filling without additional data
            state.current_step = "coordinating_form_fill"
            state.messages.append({
                "role": "assistant",
                "content": "✅ Proceeding to form filling with available data...",
                "agent": self.agent_type.value
            })
            
        elif feedback_lower == "retry":
            # Retry data extraction
            state.current_step = "coordinating_extraction"
            state.extracted_data = None
            state.messages.append({
                "role": "assistant",
                "content": "🔄 Retrying data extraction...",
                "agent": self.agent_type.value
            })
            
        else:
            # Parse field assignments (e.g., "patient_name=John Smith, doctor_name=Dr. Johnson")
            try:
                parsed_fields = self._parse_field_assignments(feedback)
                
                if parsed_fields:
                    # Add parsed fields to extracted data
                    if state.extracted_data is None:
                        state.extracted_data = {}
                    
                    state.extracted_data.update(parsed_fields)
                    
                    # Update missing fields list
                    for field_name in parsed_fields.keys():
                        if (hasattr(state, 'missing_fields_to_fill') and 
                            state.missing_fields_to_fill is not None and 
                            field_name in state.missing_fields_to_fill):
                            state.missing_fields_to_fill.remove(field_name)
                    
                    # Check if there are still missing fields
                    remaining_missing = getattr(state, 'missing_fields_to_fill', [])
                    
                    if remaining_missing:
                        # Still have missing fields - ask for more
                        remaining_message = f"""
✅ **Fields Added Successfully**

Added: {', '.join(parsed_fields.keys())}

**Still missing:**
{self._format_missing_fields_list(remaining_missing)}

Continue filling fields or type "print" to proceed with current data.
"""
                        state.messages.append({
                            "role": "assistant",
                            "content": remaining_message,
                            "agent": self.agent_type.value
                        })
                        # Stay in missing fields input mode
                        state.current_step = "awaiting_missing_fields_input"
                        state.requires_human_review = True
                        
                    else:
                        # All required fields filled - proceed to form filling
                        state.current_step = "coordinating_form_fill"
                        state.messages.append({
                            "role": "assistant",
                            "content": f"✅ All required fields completed! Added: {', '.join(parsed_fields.keys())}\n\nProceeding to form filling...",
                            "agent": self.agent_type.value
                        })
                        
                else:
                    # Invalid format
                    state.messages.append({
                        "role": "assistant",
                        "content": "❌ Invalid format. Please use: `field_name=value` or `field1=value1, field2=value2`\nOr type 'print' to proceed without missing fields.",
                        "agent": self.agent_type.value
                    })
                    # Stay in missing fields input mode
                    state.current_step = "awaiting_missing_fields_input"
                    state.requires_human_review = True
                    
            except Exception as e:
                state.messages.append({
                    "role": "assistant",
                    "content": f"❌ Error parsing input: {str(e)}\nPlease use format: `field_name=value` or type 'print' to proceed.",
                    "agent": self.agent_type.value
                })
                # Stay in missing fields input mode
                state.current_step = "awaiting_missing_fields_input"
                state.requires_human_review = True
    
    def _handle_completion_feedback(self, state: AgentState, feedback: str) -> None:
        """Handle user feedback when workflow is completed."""
        feedback_lower = feedback.lower().strip()
        
        if feedback_lower in ["1", "process another", "another", "process another document"]:
            # Reset state for processing another document
            state.current_step = "initialization"
            state.extracted_data = None
            state.filled_form_path = None
            state.form_filling_status = None
            state.pdf_file_paths = []
            state.missing_fields_to_fill = []
            
            state.messages.append({
                "role": "assistant",
                "content": "🔄 **Starting New Document Processing**\n\nPlease provide the documents you'd like to process.",
                "agent": self.agent_type.value
            })
            
        elif feedback_lower in ["2", "make corrections", "corrections", "correct"]:
            # Go back to final review for corrections
            state.current_step = "final_review"
            
            state.messages.append({
                "role": "assistant",
                "content": "🔧 **Making Corrections**\n\nWhat would you like to correct?",
                "agent": self.agent_type.value
            })
            
        elif feedback_lower in ["3", "exit", "quit", "done", "finish"]:
            # Exit the workflow
            state.current_step = "finished"
            state.requires_human_review = False
            
            state.messages.append({
                "role": "assistant",
                "content": "👋 **Session Complete**\n\nThank you for using the form filling system. Goodbye!",
                "agent": self.agent_type.value
            })
            
        else:
            # Invalid response - ask again
            state.messages.append({
                "role": "assistant",
                "content": """❌ **Invalid Option**

Please choose:
1. Process another document
2. Make corrections  
3. Exit

Please enter 1, 2, or 3.""",
                "agent": self.agent_type.value
            })
            state.requires_human_review = True
    
    def _parse_field_assignments(self, input_text: str) -> dict:
        """Parse field assignments from user input (e.g., 'field1=value1, field2=value2')."""
        assignments = {}
        
        # Split by comma and process each assignment
        parts = [part.strip() for part in input_text.split(',')]
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key and value:
                    assignments[key] = value
        
        return assignments
    
    def _format_missing_fields_list(self, missing_fields: list[str]) -> str:
        """Format missing fields list for display."""
        return '\n'.join([f"- {field}" for field in missing_fields])
    
    def _check_data_files(self) -> list[str]:
        """Check for PDF files in the data directory."""
        import os
        from src.config import config
        
        data_dir = config.DATA_DIR
        if not os.path.exists(data_dir):
            return []
        
        pdf_files = []
        for file in os.listdir(data_dir):
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(data_dir, file))
        
        return sorted(pdf_files)
    
    def _check_form_files(self) -> list[str]:
        """Check for form files (PDF and Excel) in the form directory."""
        import os
        from src.config import config
        
        form_dir = config.FORM_DIR
        if not os.path.exists(form_dir):
            return []
        
        form_files = []
        for file in os.listdir(form_dir):
            file_lower = file.lower()
            if file_lower.endswith('.pdf') or file_lower.endswith('.xlsx') or file_lower.endswith('.xlsm'):
                form_files.append(os.path.join(form_dir, file))
        
        return sorted(form_files)
    
    async def _handle_quality_correction(self, state: AgentState) -> AgentState:
        """Handle quality correction feedback and determine corrective actions."""
        
        print("🔧 Handling quality correction feedback...")
        
        if not state.quality_assessment or not state.quality_assessment.issues_found:
            print("   ⚠️  No quality issues to correct")
            state.current_step = "completed"
            return state
        
        issues = state.quality_assessment.issues_found
        critical_issues = [i for i in issues if i.severity in ["critical", "high"]]
        
        print(f"   🔍 Found {len(issues)} total issues, {len(critical_issues)} critical/high severity")
        
        # Determine correction strategy based on issue types
        semantic_issues = [i for i in issues if i.issue_type in ["semantic_mismatch", "temporal_inconsistency", "contextual_error"]]
        format_issues = [i for i in issues if i.issue_type in ["format_error", "data_type_error"]]
        
        if semantic_issues:
            print("   🔄 Semantic issues detected - need re-extraction with enhanced context")
            return await self._handle_semantic_corrections(state, semantic_issues)
        elif format_issues and any(i.severity in ["high", "critical"] for i in format_issues):
            print("   🔄 Critical format issues detected - need re-filling with corrected mappings")
            return await self._handle_format_corrections(state, format_issues)
        else:
            print("   ✅ Only minor issues remain - proceeding to completion")
            state.current_step = "completed"
            return state
    
    async def _handle_semantic_corrections(self, state: AgentState, issues: list) -> AgentState:
        """Handle semantic correction by providing enhanced context for re-extraction."""
        
        # Create enhanced context instructions based on quality issues
        correction_context = self._build_correction_context(issues, state)
        
        # Add correction instructions to state for data extractor
        state.user_instructions = (state.user_instructions or "") + f"\n\nQUALITY CORRECTION CONTEXT:\n{correction_context}"
        
        # Route back to data extraction with enhanced context
        state.current_step = "coordinating_extraction"
        state.current_agent = AgentType.DATA_EXTRACTOR
        
        # Add feedback message
        state.messages.append({
            "role": "assistant",
            "content": f"🔄 Initiating quality corrections based on {len(issues)} semantic issues. "
                      f"Re-extracting data with enhanced context instructions.",
            "agent": self.agent_type.value,
            "correction_type": "semantic",
            "issues_count": len(issues)
        })
        
        return state
    
    async def _handle_format_corrections(self, state: AgentState, issues: list) -> AgentState:
        """Handle format correction by updating field mappings and re-filling."""
        
        # Create corrected field mappings based on issues
        correction_mappings = self._build_format_corrections(issues, state)
        
        # Store corrections in state for form filler
        if not hasattr(state, 'field_corrections'):
            state.field_corrections = {}
        state.field_corrections.update(correction_mappings)
        
        # Route back to form filling with corrections
        state.current_step = "coordinating_form_fill"
        state.current_agent = AgentType.FORM_FILLER
        
        state.messages.append({
            "role": "assistant",
            "content": f"🔄 Applying format corrections for {len(issues)} issues and re-filling form.",
            "agent": self.agent_type.value,
            "correction_type": "format",
            "issues_count": len(issues)
        })
        
        return state
    
    def _build_correction_context(self, issues: list, state: AgentState) -> str:
        """Build enhanced context instructions for semantic corrections."""
        
        corrections = []
        
        for issue in issues:
            if issue.issue_type == "temporal_inconsistency":
                # Generic temporal inconsistency handling
                field_context = self._analyze_field_semantic_context(issue.field_name, state)
                corrections.append(self._build_temporal_correction(issue, field_context, state))
            
            elif issue.issue_type == "semantic_mismatch":
                corrections.append(f"- {issue.field_name}: {issue.suggestion}")
            
            elif issue.issue_type == "contextual_error":
                corrections.append(f"- {issue.field_name}: Requires context-aware extraction. {issue.suggestion}")
        
        # Add reference form context if available
        context_text = "Field Extraction Corrections:\n" + "\n".join(corrections)
        
        if state.reference_form_path:
            context_text += f"\n\nReference form available at: {state.reference_form_path}"
            context_text += "\nUse reference form context to understand correct field purposes and value types."
        
        return context_text
    
    def _build_format_corrections(self, issues: list, state: AgentState) -> dict:
        """Build format correction mappings."""
        
        corrections = {}
        
        for issue in issues:
            if issue.issue_type == "data_type_error":
                corrections[issue.field_id] = {
                    "correction_type": "data_type",
                    "expected_type": "numeric" if "numeric" in issue.suggestion else "text",
                    "suggestion": issue.suggestion
                }
            
            elif issue.issue_type == "format_error":
                corrections[issue.field_id] = {
                    "correction_type": "format",
                    "expected_pattern": issue.expected_pattern,
                    "suggestion": issue.suggestion
                }
        
        return corrections
    
    def _analyze_field_semantic_context(self, field_name: str, state: AgentState) -> Dict[str, Any]:
        """Analyze what type of date/field this is semantically."""
        field_lower = field_name.lower()
        
        context = {
            "is_document_date": any(keyword in field_lower for keyword in 
                ['eingang', 'submission', 'received', 'application', 'document', 'datum']),
            "is_personal_date": any(keyword in field_lower for keyword in 
                ['geburt', 'birth', 'born']),
            "is_deadline_date": any(keyword in field_lower for keyword in 
                ['deadline', 'due', 'frist']),
            "date_category": "unknown"
        }
        
        if context["is_document_date"]:
            context["date_category"] = "document_submission"
        elif context["is_personal_date"]:
            context["date_category"] = "personal_biographical"
        elif context["is_deadline_date"]:
            context["date_category"] = "future_deadline"
        
        return context
    
    def _build_temporal_correction(self, issue: 'QualityIssue', field_context: Dict[str, Any], state: AgentState) -> str:
        """Build generic temporal correction based on field context."""
        from datetime import datetime
        
        current_year = datetime.now().year
        current_value = str(issue.current_value) if issue.current_value else ""
        
        if field_context["date_category"] == "document_submission":
            # Find conflicting personal dates in extracted data
            birth_dates = self._find_personal_dates_in_extraction(state)
            
            correction = f"- {issue.field_name}: CRITICAL - This field expects a DOCUMENT/SUBMISSION date, not personal biographical dates."
            
            if current_value in birth_dates:
                correction += f" Current value '{current_value}' appears to be a birth date."
            
            correction += f" Look for recent dates ({current_year-1}-{current_year}) near application/submission context, document headers, or cover letter dates."
            correction += " Avoid dates from biographical sections (birth dates, graduation dates from years ago)."
            
            return correction
            
        elif field_context["date_category"] == "personal_biographical":
            return f"- {issue.field_name}: This field expects personal biographical dates (birth, graduation, etc.), not document submission dates."
            
        elif field_context["date_category"] == "future_deadline":
            return f"- {issue.field_name}: This field expects a future date (deadline, due date), not past dates."
            
        else:
            # Generic temporal correction
            return f"- {issue.field_name}: Temporal inconsistency detected. {issue.suggestion}"
    
    def _find_personal_dates_in_extraction(self, state: AgentState) -> List[str]:
        """Find dates that appear to be personal/biographical in the extracted data."""
        personal_dates = []
        
        if not state.extracted_data:
            return personal_dates
            
        for field_id, value in state.extracted_data.items():
            # Check if this looks like a personal date based on field context
            if hasattr(state, 'form_structure') and state.form_structure:
                field_info = state.form_structure.get('all_fields', {}).get(field_id, {})
                field_name = field_info.get('name', '') if isinstance(field_info, dict) else str(field_info)
                
                if any(keyword in field_name.lower() for keyword in ['geburt', 'birth', 'born']):
                    personal_dates.append(str(value))
                    
        return personal_dates
    
    def _detect_reference_form(self, form_template_path: str) -> Optional[str]:
        """Auto-detect reference form in sample directory based on template."""
        
        if not form_template_path:
            return None
        
        try:
            # Look for reference forms in sample directory
            from src.config import config
            
            # Check common sample directories
            sample_dirs = [
                os.path.join(os.path.dirname(os.path.dirname(form_template_path)), 'sample'),
                os.path.join(config.BASE_DIR, 'sample'),
                'sample'
            ]
            
            form_filename = os.path.basename(form_template_path)
            form_name_base = os.path.splitext(form_filename)[0]
            
            for sample_dir in sample_dirs:
                if not os.path.exists(sample_dir):
                    continue
                
                # Look for files with similar names or containing the form name
                for file in os.listdir(sample_dir):
                    file_lower = file.lower()
                    form_name_lower = form_name_base.lower()
                    
                    # Match files with similar names or reference patterns
                    if (form_name_lower in file_lower or 
                        file_lower.startswith(form_name_lower) or
                        any(ref_word in file_lower for ref_word in ['bewerbung', 'sample', 'reference', 'filled'])):
                        
                        reference_path = os.path.join(sample_dir, file)
                        print(f"🔗 Auto-detected reference form: {file}")
                        return reference_path
            
            return None
            
        except Exception as e:
            print(f"⚠️  Error detecting reference form: {str(e)}")
            return None
    
    def _format_file_list(self, files: list[str]) -> str:
        """Format file list for display."""
        if not files:
            return "  (none)"
        
        formatted = []
        for file in files:
            filename = os.path.basename(file)
            formatted.append(f"  - {filename}")
        
        return "\n".join(formatted)
