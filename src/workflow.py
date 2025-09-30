"""LangGraph workflow orchestrating the multi-agent form filler system."""
from typing import Dict, Any
from langgraph.graph import StateGraph, END

from src.models import AgentState, AgentType
from src.agents.orchestrator import OrchestratorAgent
from src.agents.form_learner import FormLearningAgent
from src.agents.data_extractor import DataExtractorAgent  
from src.agents.form_filler import FormFillerAgent
from src.agents.quality_checker import QualityCheckerAgent

class FormFillerWorkflow:
    """
    LangGraph workflow that coordinates the multi-agent form filling process.
    
    Workflow Steps:
    1. Orchestrator initializes and gathers requirements
    2. Form Learner analyzes target form structure 
    3. Data Extractor processes PDF documents using form insights
    4. Orchestrator reviews extraction results
    5. Form Filler creates filled forms
    6. Quality Checker validates filled forms against reference patterns
    7. Iterative improvement if quality issues found
    8. Final review and human interaction
    """
    
    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.form_learner = FormLearningAgent()
        self.data_extractor = DataExtractorAgent()
        self.form_filler = FormFillerAgent()
        self.quality_checker = QualityCheckerAgent()
        
        # Build the workflow graph
        self.workflow = self._build_workflow()
        self.app = None
    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph state graph."""
        
        # Create the state graph
        workflow = StateGraph(AgentState)
        
        # Add nodes (agents)
        workflow.add_node("orchestrator", self._orchestrator_node)
        workflow.add_node("form_learner", self._form_learner_node)
        workflow.add_node("data_extractor", self._data_extractor_node)
        workflow.add_node("form_filler", self._form_filler_node)
        workflow.add_node("quality_checker", self._quality_checker_node)
        
        # Set entry point
        workflow.set_entry_point("orchestrator")
        
        # Add conditional edges based on current step and agent
        workflow.add_conditional_edges(
            "orchestrator",
            self._route_from_orchestrator,
            {
                "form_learner": "form_learner",
                "data_extractor": "data_extractor",
                "form_filler": "form_filler",
                "quality_checker": "quality_checker",
                "end": END  # End when human input is needed
            }
        )
        
        workflow.add_conditional_edges(
            "form_learner",
            self._route_from_form_learner,
            {
                "data_extractor": "data_extractor",
                "orchestrator": "orchestrator",
                "end": END
            }
        )
        
        workflow.add_conditional_edges(
            "data_extractor", 
            self._route_from_data_extractor,
            {
                "orchestrator": "orchestrator",
                "end": END
            }
        )
        
        workflow.add_conditional_edges(
            "form_filler",
            self._route_from_form_filler, 
            {
                "quality_checker": "quality_checker",
                "orchestrator": "orchestrator",
                "end": END
            }
        )
        
        workflow.add_conditional_edges(
            "quality_checker",
            self._route_from_quality_checker,
            {
                "orchestrator": "orchestrator",
                "end": END
            }
        )
        
        return workflow
    
    async def _orchestrator_node(self, state: AgentState) -> AgentState:
        """Orchestrator agent node."""
        return await self.orchestrator.process(state)
    
    async def _form_learner_node(self, state: AgentState) -> AgentState:
        """Form learner agent node."""
        return await self.form_learner.process(state)
    
    async def _data_extractor_node(self, state: AgentState) -> AgentState:
        """Data extractor agent node."""
        return await self.data_extractor.process(state)
    
    async def _form_filler_node(self, state: AgentState) -> AgentState:
        """Form filler agent node.""" 
        return await self.form_filler.process(state)
    
    async def _quality_checker_node(self, state: AgentState) -> AgentState:
        """Quality checker agent node."""
        return await self.quality_checker.process(state)
    
    def _route_from_orchestrator(self, state: AgentState) -> str:
        """Route from orchestrator based on current step."""
        
        print(f"🔀 Routing from orchestrator: step={state.current_step}, agent={state.current_agent}, requires_review={state.requires_human_review}")
        
        if state.requires_human_review:
            print("   → Ending for human review")
            return "end"  # End workflow when human input is needed
        elif state.current_agent == AgentType.FORM_LEARNER:
            print("   → Routing to form_learner")
            return "form_learner"
        elif state.current_agent == AgentType.DATA_EXTRACTOR:
            print("   → Routing to data_extractor")
            return "data_extractor"
        elif state.current_agent == AgentType.FORM_FILLER:
            print("   → Routing to form_filler")
            return "form_filler"
        elif state.current_agent == AgentType.QUALITY_CHECKER:
            print("   → Routing to quality_checker")
            return "quality_checker"
        elif state.current_step == "completed":
            print("   → Ending - workflow completed")
            return "end"
        else:
            print("   → Ending - default case")
            return "end"  # Default to end if unclear
    
    def _route_from_form_learner(self, state: AgentState) -> str:
        """Route from form learner."""
        print(f"🔀 Routing from form_learner: step={state.current_step}, agent={state.current_agent}")
        
        if state.requires_human_review:
            print("   → Ending for human review")
            return "end"
        elif state.current_agent == AgentType.DATA_EXTRACTOR:
            print("   → Routing to data_extractor")
            return "data_extractor"
        elif state.current_agent == AgentType.ORCHESTRATOR:
            print("   → Routing to orchestrator")
            return "orchestrator"
        else:
            print("   → Ending - default from form_learner")
            return "end"
    
    def _route_from_data_extractor(self, state: AgentState) -> str:
        """Route from data extractor."""
        if state.current_agent == AgentType.ORCHESTRATOR:
            return "orchestrator"
        else:
            return "end"
    
    def _route_from_form_filler(self, state: AgentState) -> str:
        """Route from form filler."""
        print(f"🔀 Routing from form_filler: step={state.current_step}, agent={state.current_agent}")
        
        # Priority: Check step first to ensure quality checking happens
        if state.current_step == "final_review":
            # After form filling, go to quality checker
            print("   → Routing to quality_checker for validation")
            return "quality_checker"
        elif state.current_agent == AgentType.ORCHESTRATOR:
            print("   → Routing to orchestrator")
            return "orchestrator"
        else:
            print("   → Ending - default from form_filler")
            return "end"
    
    def _route_from_quality_checker(self, state: AgentState) -> str:
        """Route from quality checker."""
        print(f"🔀 Routing from quality_checker: step={state.current_step}, agent={state.current_agent}")
        
        if state.current_agent == AgentType.ORCHESTRATOR:
            print("   → Routing to orchestrator for correction handling")
            return "orchestrator"
        else:
            print("   → Ending - quality check completed")
            return "end"
    

    
    def compile(self):
        """Compile the workflow."""
        self.app = self.workflow.compile()
        return self.app
    
    async def run(self, initial_state: AgentState = None) -> AgentState:
        """Run the complete workflow."""
        
        if not self.app:
            self.compile()
        
        if initial_state is None:
            initial_state = AgentState()
        
        try:
            # Convert AgentState to dict for LangGraph
            state_dict = initial_state.dict()
            
            # Run the workflow
            final_state_dict = await self.app.ainvoke(state_dict)
            
            # Convert back to AgentState
            final_state = AgentState(**final_state_dict)
            return final_state
            
        except Exception as e:
            print(f"❌ Workflow error: {str(e)}")
            # Return error state
            error_state = initial_state or AgentState()
            error_state.messages.append({
                "role": "assistant",
                "content": f"❌ Workflow failed: {str(e)}",
                "agent": "system",
                "error": str(e)
            })
            return error_state
    
    def process_human_feedback(self, state: AgentState, feedback: str) -> AgentState:
        """Process human feedback and update state."""
        updated_state = self.orchestrator.handle_human_feedback(state, feedback)
        return updated_state


# Module-level function for LangGraph Studio
def create_form_filler_graph():
    """
    Create and return the compiled form filler graph for LangGraph Studio.
    
    This graph orchestrates a multi-agent workflow for intelligent form filling:
    1. Orchestrator - Manages the workflow and user interactions
    2. Data Extractor - Extracts data from PDF documents using Azure Document Intelligence
    3. Form Filler - Fills PDF and Excel forms with intelligent field mapping
    
    The workflow supports both PDF and Excel (.xlsm) forms with semantic field matching.
    """
    workflow = FormFillerWorkflow()
    compiled_graph = workflow.compile()
    
    # Add metadata for better Studio visualization
    compiled_graph._metadata = {
        "name": "Multi-Agent Form Filler",
        "description": "Intelligent form filling system supporting PDF and Excel forms",
        "version": "1.0",
        "agents": ["Orchestrator", "Data Extractor", "Form Filler"],
        "supported_formats": ["PDF", "Excel (.xlsx/.xlsm)"],
        "features": ["Azure Document Intelligence", "Semantic Field Mapping", "Macro Preservation"]
    }
    
    return compiled_graph
