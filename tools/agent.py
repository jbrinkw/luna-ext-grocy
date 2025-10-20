"""LangGraph ReAct agent for Grocy tools.

This agent provides both single-turn and interactive chat modes for managing
Grocy inventory, recipes, meal plans, and shopping lists using LangGraph.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Callable, Tuple
from pathlib import Path

from dotenv import load_dotenv
from langchain.tools import Tool, StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# Add tools directory to path
_tools_path = Path(__file__).parent
if str(_tools_path) not in sys.path:
    sys.path.insert(0, str(_tools_path))

# Import all tools from grocy_tools
from grocy_tools import (
    # Inventory
    GROCY_GET_Inventory,
    GROCY_GET_InventoryArgs,
    GROCY_UPDATE_AddProductQuantity,
    GROCY_UPDATE_AddProductQuantityArgs,
    GROCY_UPDATE_ConsumeProduct,
    GROCY_UPDATE_ConsumeProductArgs,
    
    # Products
    GROCY_GET_Products,
    GROCY_GET_ProductsArgs,
    GROCY_ACTION_CreateProduct,
    GROCY_ACTION_CreateProductArgs,
    GROCY_ACTION_CreatePlaceholder,
    GROCY_ACTION_CreatePlaceholderArgs,
    
    # Shopping List
    GROCY_GET_ShoppingList,
    GROCY_GET_ShoppingListArgs,
    GROCY_ACTION_AddToShoppingList,
    GROCY_ACTION_AddToShoppingListArgs,
    GROCY_ACTION_RemoveFromShoppingList,
    GROCY_ACTION_RemoveFromShoppingListArgs,
    GROCY_ACTION_ClearShoppingList,
    GROCY_ACTION_ClearShoppingListArgs,
    
    # Meal Plan
    GROCY_GET_MealPlan,
    GROCY_GET_MealPlanArgs,
    GROCY_ACTION_AddMealToPlan,
    GROCY_ACTION_AddMealToPlanArgs,
    GROCY_ACTION_MarkMealDone,
    GROCY_ACTION_MarkMealDoneArgs,
    GROCY_ACTION_DeleteMealPlanEntry,
    GROCY_ACTION_DeleteMealPlanEntryArgs,
    
    # Recipes
    GROCY_GET_Recipes,
    GROCY_GET_RecipesArgs,
    GROCY_GET_Recipe,
    GROCY_GET_RecipeArgs,
    GROCY_ACTION_CreateRecipe,
    GROCY_ACTION_CreateRecipeArgs,
    GROCY_ACTION_AddRecipeIngredient,
    GROCY_ACTION_AddRecipeIngredientArgs,
    GROCY_GET_CookableRecipes,
    GROCY_GET_CookableRecipesArgs,
    
    # Macro Tracking
    GROCY_GET_DayMacros,
    GROCY_GET_DayMacrosArgs,
    GROCY_ACTION_CreateTempItem,
    GROCY_ACTION_CreateTempItemArgs,
    GROCY_ACTION_DeleteTempItem,
    GROCY_ACTION_DeleteTempItemArgs,
    GROCY_ACTION_SetProductPrice,
    GROCY_ACTION_SetProductPriceArgs,
    
    SYSTEM_PROMPT,
)


# Tool call logging
TOOL_CALL_LOG: List[Dict[str, Any]] = []


def _log_tool_call_entry(tool: str, args: Any, result: Optional[Any] = None, error: Optional[str] = None) -> None:
    """Log a tool call for debugging/tracking."""
    entry: Dict[str, Any] = {"tool": tool, "args": args}
    if error is None:
        entry["result"] = result
    else:
        entry["error"] = error
    try:
        TOOL_CALL_LOG.append(entry)
    except Exception:
        pass


def _wrap_tool_with_logging(tool_name: str, tool_func: Callable, args_schema=None) -> Callable:
    """Wrap a tool function to handle Grocy (bool, str) format and add logging."""
    def wrapper(**kwargs) -> str:
        try:
            success, result = tool_func(**kwargs)
            _log_tool_call_entry(tool_name, kwargs, result=result)
            if not success:
                return json.dumps({"status": "error", "message": result})
            return result
        except Exception as exc:
            error_msg = str(exc)
            _log_tool_call_entry(tool_name, kwargs, error=error_msg)
            return json.dumps({"status": "error", "message": error_msg})
    return wrapper


def get_tools() -> List[Tool]:
    """Build LangChain tools from Grocy tool functions."""
    
    tools = []
    
    # Inventory tools
    tools.append(StructuredTool(
        name="GetInventory",
        func=_wrap_tool_with_logging("GetInventory", GROCY_GET_Inventory),
        description=GROCY_GET_Inventory.__doc__ or "Get current inventory",
        args_schema=GROCY_GET_InventoryArgs,
    ))
    
    tools.append(StructuredTool(
        name="AddProductQuantity",
        func=_wrap_tool_with_logging("AddProductQuantity", GROCY_UPDATE_AddProductQuantity),
        description=GROCY_UPDATE_AddProductQuantity.__doc__ or "Add product quantity to inventory",
        args_schema=GROCY_UPDATE_AddProductQuantityArgs,
    ))
    
    tools.append(StructuredTool(
        name="ConsumeProduct",
        func=_wrap_tool_with_logging("ConsumeProduct", GROCY_UPDATE_ConsumeProduct),
        description=GROCY_UPDATE_ConsumeProduct.__doc__ or "Consume product from inventory",
        args_schema=GROCY_UPDATE_ConsumeProductArgs,
    ))
    
    # Product tools
    tools.append(StructuredTool(
        name="GetProducts",
        func=_wrap_tool_with_logging("GetProducts", GROCY_GET_Products),
        description=GROCY_GET_Products.__doc__ or "Get all products",
        args_schema=GROCY_GET_ProductsArgs,
    ))
    
    tools.append(StructuredTool(
        name="CreateProduct",
        func=_wrap_tool_with_logging("CreateProduct", GROCY_ACTION_CreateProduct),
        description=GROCY_ACTION_CreateProduct.__doc__ or "Create a new product",
        args_schema=GROCY_ACTION_CreateProductArgs,
    ))
    
    tools.append(StructuredTool(
        name="CreatePlaceholder",
        func=_wrap_tool_with_logging("CreatePlaceholder", GROCY_ACTION_CreatePlaceholder),
        description=GROCY_ACTION_CreatePlaceholder.__doc__ or "Create a placeholder product",
        args_schema=GROCY_ACTION_CreatePlaceholderArgs,
    ))
    
    # Shopping list tools
    tools.append(StructuredTool(
        name="GetShoppingList",
        func=_wrap_tool_with_logging("GetShoppingList", GROCY_GET_ShoppingList),
        description=GROCY_GET_ShoppingList.__doc__ or "Get shopping list items",
        args_schema=GROCY_GET_ShoppingListArgs,
    ))
    
    tools.append(StructuredTool(
        name="AddToShoppingList",
        func=_wrap_tool_with_logging("AddToShoppingList", GROCY_ACTION_AddToShoppingList),
        description=GROCY_ACTION_AddToShoppingList.__doc__ or "Add product to shopping list",
        args_schema=GROCY_ACTION_AddToShoppingListArgs,
    ))
    
    tools.append(StructuredTool(
        name="RemoveFromShoppingList",
        func=_wrap_tool_with_logging("RemoveFromShoppingList", GROCY_ACTION_RemoveFromShoppingList),
        description=GROCY_ACTION_RemoveFromShoppingList.__doc__ or "Remove product from shopping list",
        args_schema=GROCY_ACTION_RemoveFromShoppingListArgs,
    ))
    
    tools.append(StructuredTool(
        name="ClearShoppingList",
        func=_wrap_tool_with_logging("ClearShoppingList", GROCY_ACTION_ClearShoppingList),
        description=GROCY_ACTION_ClearShoppingList.__doc__ or "Clear shopping list",
        args_schema=GROCY_ACTION_ClearShoppingListArgs,
    ))
    
    # Meal plan tools
    tools.append(StructuredTool(
        name="GetMealPlan",
        func=_wrap_tool_with_logging("GetMealPlan", GROCY_GET_MealPlan),
        description=GROCY_GET_MealPlan.__doc__ or "Get meal plan entries",
        args_schema=GROCY_GET_MealPlanArgs,
    ))
    
    tools.append(StructuredTool(
        name="AddMealToPlan",
        func=_wrap_tool_with_logging("AddMealToPlan", GROCY_ACTION_AddMealToPlan),
        description=GROCY_ACTION_AddMealToPlan.__doc__ or "Add meal to plan",
        args_schema=GROCY_ACTION_AddMealToPlanArgs,
    ))
    
    tools.append(StructuredTool(
        name="MarkMealDone",
        func=_wrap_tool_with_logging("MarkMealDone", GROCY_ACTION_MarkMealDone),
        description=GROCY_ACTION_MarkMealDone.__doc__ or "Mark meal plan entry as done",
        args_schema=GROCY_ACTION_MarkMealDoneArgs,
    ))
    
    tools.append(StructuredTool(
        name="DeleteMealPlanEntry",
        func=_wrap_tool_with_logging("DeleteMealPlanEntry", GROCY_ACTION_DeleteMealPlanEntry),
        description=GROCY_ACTION_DeleteMealPlanEntry.__doc__ or "Delete meal plan entry",
        args_schema=GROCY_ACTION_DeleteMealPlanEntryArgs,
    ))
    
    # Recipe tools
    tools.append(StructuredTool(
        name="GetRecipes",
        func=_wrap_tool_with_logging("GetRecipes", GROCY_GET_Recipes),
        description=GROCY_GET_Recipes.__doc__ or "Get all recipes",
        args_schema=GROCY_GET_RecipesArgs,
    ))
    
    tools.append(StructuredTool(
        name="GetRecipe",
        func=_wrap_tool_with_logging("GetRecipe", GROCY_GET_Recipe),
        description=GROCY_GET_Recipe.__doc__ or "Get recipe details",
        args_schema=GROCY_GET_RecipeArgs,
    ))
    
    tools.append(StructuredTool(
        name="CreateRecipe",
        func=_wrap_tool_with_logging("CreateRecipe", GROCY_ACTION_CreateRecipe),
        description=GROCY_ACTION_CreateRecipe.__doc__ or "Create a new recipe",
        args_schema=GROCY_ACTION_CreateRecipeArgs,
    ))
    
    tools.append(StructuredTool(
        name="AddRecipeIngredient",
        func=_wrap_tool_with_logging("AddRecipeIngredient", GROCY_ACTION_AddRecipeIngredient),
        description=GROCY_ACTION_AddRecipeIngredient.__doc__ or "Add ingredient to recipe",
        args_schema=GROCY_ACTION_AddRecipeIngredientArgs,
    ))
    
    tools.append(StructuredTool(
        name="GetCookableRecipes",
        func=_wrap_tool_with_logging("GetCookableRecipes", GROCY_GET_CookableRecipes),
        description=GROCY_GET_CookableRecipes.__doc__ or "Get recipes that can be cooked now",
        args_schema=GROCY_GET_CookableRecipesArgs,
    ))
    
    # Macro tracking tools
    tools.append(StructuredTool(
        name="GetDayMacros",
        func=_wrap_tool_with_logging("GetDayMacros", GROCY_GET_DayMacros),
        description=GROCY_GET_DayMacros.__doc__ or "Get macro totals for a day",
        args_schema=GROCY_GET_DayMacrosArgs,
    ))
    
    tools.append(StructuredTool(
        name="CreateTempItem",
        func=_wrap_tool_with_logging("CreateTempItem", GROCY_ACTION_CreateTempItem),
        description=GROCY_ACTION_CreateTempItem.__doc__ or "Log temporary consumed item",
        args_schema=GROCY_ACTION_CreateTempItemArgs,
    ))
    
    tools.append(StructuredTool(
        name="DeleteTempItem",
        func=_wrap_tool_with_logging("DeleteTempItem", GROCY_ACTION_DeleteTempItem),
        description=GROCY_ACTION_DeleteTempItem.__doc__ or "Delete temporary item",
        args_schema=GROCY_ACTION_DeleteTempItemArgs,
    ))
    
    tools.append(StructuredTool(
        name="SetProductPrice",
        func=_wrap_tool_with_logging("SetProductPrice", GROCY_ACTION_SetProductPrice),
        description=GROCY_ACTION_SetProductPrice.__doc__ or "Set product price",
        args_schema=GROCY_ACTION_SetProductPriceArgs,
    ))
    
    return tools


def _build_system_prompt() -> str:
    """Build the system prompt with product context."""
    base_prompt = (
        "You are a helpful Grocy assistant. "
        "Use tools to manage inventory, recipes, meal plans, and shopping lists. "
        "Return concise, clear answers.\n\n"
    )
    
    # Add product list context
    try:
        success, products_json = GROCY_GET_Products()
        if success:
            products = json.loads(products_json)
            product_list = ", ".join([f"{p['name']} (id={p['id']})" for p in products[:20]])
            if len(products) > 20:
                product_list += f"... and {len(products) - 20} more"
            base_prompt += f"\nKnown Products: {product_list}\n\n"
    except Exception:
        pass
    
    base_prompt += SYSTEM_PROMPT
    
    return base_prompt


def build_agent(model_name: str = "gpt-4o-mini", temperature: float = 0.0):
    """Create a ReAct agent with Grocy tools.
    
    Args:
        model_name: OpenAI model name (default: gpt-4o-mini)
        temperature: LLM temperature (default: 0.0)
    
    Returns:
        LangGraph agent executor
    """
    tools = get_tools()
    llm = ChatOpenAI(model=model_name, temperature=temperature)
    agent = create_react_agent(llm, tools)
    return agent


def run_question(question: str, model_name: str = "gpt-4o-mini", temperature: float = 0.0) -> str:
    """Run a single-turn question through the agent.
    
    Args:
        question: User question
        model_name: OpenAI model name
        temperature: LLM temperature
    
    Returns:
        Agent response with tool call log
    """
    agent = build_agent(model_name=model_name, temperature=temperature)
    TOOL_CALL_LOG.clear()
    system_prompt = _build_system_prompt()
    
    final = agent.invoke({
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=question)
        ]
    })
    
    messages = final.get("messages", [])
    answer = messages[-1].content if messages else str(final)
    
    try:
        tools_summary = json.dumps(TOOL_CALL_LOG, ensure_ascii=False, indent=2)
    except Exception:
        tools_summary = str(TOOL_CALL_LOG)
    
    return f"{answer}\n\n--- Tool Calls ---\n{tools_summary}"


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for agent CLI.
    
    Supports both single-turn mode (--question) and interactive chat.
    """
    parser = argparse.ArgumentParser(
        description="Run LangGraph ReAct agent for Grocy (interactive chat by default)"
    )
    parser.add_argument(
        "--question", 
        help="Single-turn question (skip for interactive chat)"
    )
    parser.add_argument(
        "--model", 
        default="gpt-4o-mini", 
        help="LLM model name (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--temperature", 
        type=float, 
        default=0.0, 
        help="LLM temperature (default: 0.0)"
    )
    args = parser.parse_args(argv)

    # Load environment variables
    load_dotenv()

    # Validate required environment variables
    if not os.getenv("GROCY_API_KEY"):
        print("Warning: GROCY_API_KEY not set; tool calls will fail.")
    if not os.getenv("GROCY_BASE_URL"):
        print("Warning: GROCY_BASE_URL not set; tool calls will fail.")
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set.")
        return 1

    # Single-turn mode
    if args.question:
        try:
            answer = run_question(
                args.question, 
                model_name=args.model, 
                temperature=args.temperature
            )
            print(answer)
            return 0
        except Exception as err:
            print(f"Agent error: {err}")
            return 1

    # Interactive chat (REPL)
    print(f"Grocy Agent Chat (model: {args.model})")
    print("Type 'exit' or 'quit' to leave.\n")
    
    agent = build_agent(model_name=args.model, temperature=args.temperature)
    history = [SystemMessage(content=_build_system_prompt())]
    
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print()
                break
            
            if not user_input:
                continue
            
            if user_input.lower() in {"exit", "quit"}:
                break
            
            try:
                TOOL_CALL_LOG.clear()
                result = agent.invoke({
                    "messages": history + [HumanMessage(content=user_input)]
                })
                
                messages = result.get("messages", [])
                answer = messages[-1].content if messages else str(result)
                history = messages or (history + [HumanMessage(content=user_input)])
                
                print(f"\nAgent: {answer}\n")
                
                if TOOL_CALL_LOG:
                    try:
                        tools_summary = json.dumps(TOOL_CALL_LOG, ensure_ascii=False, indent=2)
                    except Exception:
                        tools_summary = str(TOOL_CALL_LOG)
                    print(f"[Tools called: {len(TOOL_CALL_LOG)}]\n{tools_summary}\n")
                
            except KeyboardInterrupt:
                print()
                break
            except Exception as err:
                print(f"Agent error: {err}\n")
                
    except KeyboardInterrupt:
        print()
    
    print("Goodbye!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

