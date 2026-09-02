import os
from typing import Literal, Optional, List
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph, START, END

# --- 1. Schemas & State Definition ---

class ExtractedEntity(BaseModel):
    name: str = Field(description="Name of the company or business")
    location: str = Field(description="City or region within the target country")
    products: List[str] = Field(description="Main products or services offered/procured")
    website: Optional[str] = Field(None, description="Official website URL")
    contact_email: Optional[str] = Field(None, description="Contact email if found")
    summary: str = Field(description="Brief summary of their business profile")

class ExtractionResult(BaseModel):
    results: List[ExtractedEntity] = Field(description="List of discovered entities")

class AgentState(TypedDict):
    query: str
    country: Optional[str]
    entity_type: Optional[Literal["buyer", "supplier"]]
    search_results: Optional[str]
    extracted_data: Optional[List[dict]]
    awaiting_user_input: bool
    system_message: Optional[str]

# --- 2. Node Definitions ---

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def validate_config_node(state: AgentState):
    """
    Mandatory Gate: Checks if country and entity_type are supplied.
    If missing, sets a flag and system message to prompt user selection.
    """
    country = state.get("country")
    entity_type = state.get("entity_type")

    missing = []
    if not country:
        missing.append("Target Country (e.g., India, USA, Germany)")
    if not entity_type or entity_type.lower() not in ["buyer", "supplier"]:
        missing.append("Entity Role ('buyer' or 'supplier')")

    if missing:
        return {
            "awaiting_user_input": True,
            "system_message": f"Action paused. Mandatory selection required: {', '.join(missing)}."
        }
    
    return {
        "awaiting_user_input": False,
        "system_message": None,
        "entity_type": entity_type.lower()
    }

def search_node(state: AgentState):
    """
    Executes a contextualized search based on validated parameters.
    """
    country = state["country"]
    entity_type = state["entity_type"]
    product = state["query"]

    # Parameterized query generation
    if entity_type == "buyer":
        search_query = f"top {product} buyers importers procurement companies in {country} directory contact"
    else:
        search_query = f"verified {product} manufacturers suppliers exporters in {country} directory catalog"

    # Tavily tool integration (or fallback mock)
    try:
        tool = TavilySearchResults(max_results=5)
        raw_results = tool.invoke({"query": search_query})
        formatted_results = "\n\n".join([f"Source: {r.get('url')}\nContent: {r.get('content')}" for r in raw_results])
    except Exception:
        # Fallback if Tavily API key is not set in environment
        formatted_results = f"[Mock web search results for: '{search_query}']"

    return {"search_results": formatted_results}

def extract_node(state: AgentState):
    """
    Parses unstructured web search output into structured JSON entities.
    """
    parser = PydanticOutputParser(pydantic_object=ExtractionResult)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert market research assistant. Extract verified company profiles from raw search results.\n{format_instructions}"),
        ("user", "Target: {entity_type}s in {country}\nProduct/Service: {query}\n\nSearch Results:\n{search_results}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        structured_response = chain.invoke({
            "entity_type": state["entity_type"],
            "country": state["country"],
            "query": state["query"],
            "search_results": state["search_results"],
            "format_instructions": parser.get_format_instructions()
        })
        extracted_list = [entity.model_dump() for entity in structured_response.results]
    except Exception as e:
        extracted_list = [{"error": f"Extraction parsing failed: {str(e)}"}]

    return {"extracted_data": extracted_list}

# --- 3. Conditional Router ---

def check_validation_router(state: AgentState) -> Literal["search_node", "__end__"]:
    if state.get("awaiting_user_input"):
        return END
    return "search_node"

# --- 4. Build and Compile Graph ---

workflow = StateGraph(AgentState)

workflow.add_node("validate_config_node", validate_config_node)
workflow.add_node("search_node", search_node)
workflow.add_node("extract_node", extract_node)

# Flow
workflow.add_edge(START, "validate_config_node")
workflow.add_conditional_edges(
    "validate_config_node",
    check_validation_router,
    {
        "search_node": "search_node",
        END: END
    }
)
workflow.add_edge("search_node", "extract_node")
workflow.add_edge("extract_node", END)

app = workflow.compile()