# Grocy Extension for Luna

A comprehensive extension for managing food inventory, meal planning, nutrition tracking, and shopping lists using [Grocy](https://grocy.info/).

## Overview

This extension provides powerful tools for:

- **Inventory Management**: Track food products, quantities, and expiry dates
- **Meal Planning**: Plan meals with recipes or individual products
- **Macro Tracking**: Monitor daily nutrition (calories, protein, carbs, fats)
- **Shopping Lists**: Manage shopping lists with Walmart integration for pricing
- **Recipe Management**: Create and manage recipes with ingredients and nutrition data
- **Placeholder Products**: Plan recipes before purchasing ingredients

## Features

### Tools Available

The extension exposes 23 tools for agent use:

#### Inventory Tools
- `GROCY_GET_Inventory` - Get current inventory with quantities and expiry dates
- `GROCY_UPDATE_AddProductQuantity` - Add stock to inventory (purchase)
- `GROCY_UPDATE_ConsumeProduct` - Remove stock from inventory (consume)

#### Product Tools
- `GROCY_GET_Products` - List all products
- `GROCY_ACTION_CreateProduct` - Create new product
- `GROCY_ACTION_CreatePlaceholder` - Create placeholder product for planning

#### Shopping List Tools
- `GROCY_GET_ShoppingList` - Get shopping list items
- `GROCY_ACTION_AddToShoppingList` - Add product to shopping list
- `GROCY_ACTION_RemoveFromShoppingList` - Remove product from shopping list
- `GROCY_ACTION_ClearShoppingList` - Clear entire shopping list

#### Meal Plan Tools
- `GROCY_GET_MealPlan` - Get meal plan for date range
- `GROCY_ACTION_AddMealToPlan` - Add meal (recipe or product) to plan
- `GROCY_ACTION_MarkMealDone` - Mark meal as consumed
- `GROCY_ACTION_DeleteMealPlanEntry` - Delete meal plan entry

#### Recipe Tools
- `GROCY_GET_Recipes` - List all recipes
- `GROCY_GET_Recipe` - Get recipe details with ingredients
- `GROCY_ACTION_CreateRecipe` - Create new recipe
- `GROCY_ACTION_AddRecipeIngredient` - Add ingredient to recipe
- `GROCY_GET_CookableRecipes` - Get recipes cookable with current inventory

#### Macro Tracking Tools
- `GROCY_GET_DayMacros` - Get consumed/planned/goal macros for a day
- `GROCY_ACTION_CreateTempItem` - Log temporary consumed item
- `GROCY_ACTION_DeleteTempItem` - Delete temporary item
- `GROCY_ACTION_SetProductPrice` - Set product price

### Web UI

The extension includes a comprehensive web dashboard with:

- **Barcode Scanner**: Quick add/remove inventory via barcode scanning
- **Inventory Dashboard**: Real-time status of inventory, prices, and shopping needs
- **Shopping List Manager**: Build shopping lists with Walmart pricing
- **Macro Tracker**: Daily view of consumed vs planned vs goal macros
- **Recipe Manager**: Create and manage recipes with nutrition data
- **Meal Planner**: Visual meal planning interface

## Required Environment Variables

Configure these in your Luna `.env` file:

```env
# Grocy Server
GROCY_BASE_URL=http://your-grocy-server/api
GROCY_API_KEY=your_grocy_api_key
GROCY_DEFAULT_LOCATION_ID=2
GROCY_DEFAULT_QU_ID_PURCHASE=2
GROCY_DEFAULT_QU_ID_STOCK=2

# OpenAI (for placeholder matching)
OPENAI_API_KEY=your_openai_key

# Nutritionix (for barcode nutrition lookup)
NUTRITIONIX_APP_ID=your_nutritionix_app_id
NUTRITIONIX_APP_KEY=your_nutritionix_app_key

# Postgres (Luna's database)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=luna
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password

# Optional: Macro goals (defaults shown)
MACRO_GOAL_CALORIES=3500
MACRO_GOAL_CARBS=350
MACRO_GOAL_FATS=100
MACRO_GOAL_PROTEIN=250
```

## Installation

1. Add the extension to Luna by local path or GitHub URL
2. Luna Hub will automatically:
   - Install Python dependencies from `requirements.txt`
   - Install Node.js dependencies for the UI
   - Initialize Postgres database tables
   - Start the web UI on an assigned port

## Key Concepts

### Placeholder Products

Placeholders are planning items (not real inventory) used for:
- Recipe ingredients before purchasing
- Shopping list items before scanning

**Important**: 
- Cannot add stock to or consume from placeholders
- When you scan a real product, it can automatically override the placeholder
- Placeholders help with meal planning before shopping

### Macro Tracking

Tracks nutrition in three categories:
- **Consumed**: Meal plan entries marked done + temporary items
- **Planned**: All meal plan entries (represents daily goal)
- **Goal**: Environment variable or database defaults

Products store per-serving macros in userfields:
- `Calories_Per_Serving`
- `Carbs` (grams)
- `Fats` (grams)
- `Protein` (grams)

### Price Management

Product prices are stored using Grocy's stock transaction pattern:
1. Add 1 unit at the specified price
2. Consume 1 unit (no net stock change)
3. Price is now recorded and queryable

## Database Tables

The extension creates these Postgres tables:

### grocy_temp_items
Temporary macro tracking items (not in Grocy inventory):
- `id` - Serial primary key
- `name` - Item name
- `calories`, `carbs`, `fats`, `protein` - Nutrition values
- `day` - Date (YYYY-MM-DD)
- `created_at` - Timestamp

### grocy_config
Configuration key-value storage:
- `key` - Configuration key (primary key)
- `value` - Configuration value

## Standalone Scripts

Reference scripts in `scripts/` folder:

- `add_below_min_to_shopping.py` - Add below-minimum stock items to shopping list
- `add_placeholders_to_shopping.py` - Add all placeholders to shopping list
- `auto_delete_broken_entries.py` - Clean up broken meal plan entries
- `build_cart_links_from_shopping_list.py` - Generate Walmart cart links
- `update_recipe_macros.py` - Update recipe nutrition from ingredients
- `scrape_walmart_search.py` - Search Walmart for products
- `scrape_walmart_product.py` - Scrape Walmart product details

## LangGraph Agent

The extension includes a standalone LangGraph ReAct agent for natural language interaction. See `tools/README.md` for details.

### Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
export GROCY_BASE_URL=https://your-grocy-instance.com
export GROCY_API_KEY=your_api_key
export OPENAI_API_KEY=your_openai_key

# Run interactive chat
cd tools
python agent.py

# Or single-turn query
python agent.py --question "what's in my inventory?"
```

### Features

- **Interactive Chat**: Multi-turn conversations with context
- **Single-Turn Mode**: Quick queries for automation
- **Tool Call Logging**: See which tools were used and their results
- **Flexible Model Selection**: Use any OpenAI model (gpt-4, gpt-4o-mini, etc.)

Example conversations:
```
You: what's in my inventory?
Agent: [Shows inventory with products, quantities, and expiry]

You: add 2 milk to shopping list
Agent: Added product to shopping list

You: show me recipes I can make right now
Agent: [Lists cookable recipes based on inventory]
```

See `tools/example_agent_usage.py` for programmatic usage examples.

## Integration with Luna Agents

All tools are accessible to Luna agents via the standard tool interface. Example agent prompts:

```
"What's in my inventory?"
"Add 2 milk to my shopping list"
"Show me my macros for today"
"Create a recipe called Protein Oatmeal"
"What recipes can I make right now?"
"Mark meal plan entry 15 as done"
```

## Development

### Project Structure

```
grocy/
├── config.json              # Extension manifest
├── requirements.txt         # Python dependencies
├── readme.md               # This file
├── tools/                  # Luna tool definitions
│   ├── grocy_tools.py      # Tool implementations
│   ├── tool_config.json    # MCP exposure settings
│   ├── agent.py            # LangGraph ReAct agent
│   ├── example_agent_usage.py  # Agent examples
│   └── README.md           # Agent documentation
├── lib/                    # Shared library code
│   ├── core/              # GrocyClient
│   ├── services/          # Domain services
│   ├── integrations/      # External integrations
│   ├── macro_tracking/    # Macro aggregation
│   └── db.py             # Postgres connection
├── ui/                     # Web interface
│   ├── server.js          # Express server
│   ├── start.sh           # Startup script
│   ├── public/            # HTML/CSS/JS
│   └── lib/              # Node.js modules
└── scripts/               # Standalone utilities
```

### Library Modules

**core/client.py** - `GrocyClient` class wrapping Grocy REST API

**services/** - Domain-specific operations:
- `inventory.py` - Inventory management
- `products.py` - Product operations
- `shopping.py` - Shopping list operations
- `recipes.py` - Recipe management
- `meal_plan.py` - Meal planning
- `userfields.py` - Custom field management

**integrations/** - External system integrations:
- `macros.py` - Macro tracking integration
- `walmart.py` - Walmart scraping/pricing

**macro_tracking/** - Macro aggregation logic:
- `macro_aggregator.py` - Combine Grocy + temp items
- `macro_db.py` - Database operations
- `day_utils.py` - Date/time utilities
- `placeholder_matcher.py` - GPT-based placeholder matching

## License

This extension integrates with Grocy, an open-source groceries & household management system.

## Support

For issues or questions:
1. Check Grocy documentation at https://grocy.info/
2. Verify environment variables are set correctly
3. Check Luna Hub logs for connection errors
4. Ensure Grocy server is accessible from Luna




