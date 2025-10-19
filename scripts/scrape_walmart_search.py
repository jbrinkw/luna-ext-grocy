from serpapi import GoogleSearch
from pydantic import BaseModel
from typing import Optional, List
import json


class WalmartSearchProduct(BaseModel):
    """Pydantic model for Walmart search result product"""
    name: Optional[str] = None
    price: Optional[str] = None
    price_per_unit: Optional[str] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None


class WalmartSearchResults(BaseModel):
    """Pydantic model for Walmart search results"""
    query: str
    search_url: str
    products: List[WalmartSearchProduct]
    search_information: Optional[dict] = None
    search_metadata: Optional[dict] = None
    search_parameters: Optional[dict] = None


def scrape_walmart_search(query: str, max_results: int = 4, store_id: str = "5879") -> WalmartSearchResults:
    """
    Search Walmart using SerpApi's Walmart Search API
    
    Args:
        query: The search query string
        max_results: Maximum number of products to return (default: 4)
        store_id: Walmart store ID for local inventory (default: "5879")
        
    Returns:
        WalmartSearchResults: Parsed search results with product information
    """
    # Hardcoded API keys
    SERPAPI_KEY = "1537bd3f00ae2dc56f437f67ee0a3d178936c0d4b6c1ce3f520f513c7e6f842f"
    
    # Parameters for SerpApi Walmart Search
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "walmart",
        "query": query,
        "store_id": store_id,
        "sort": "best_match",  # Sort by best match for most relevant results
        "no_cache": "true",  # Disable caching to get fresh results
    }
    
    print(f"Searching for: {query}")
    print(f"Using SerpApi Walmart Search API (Store: {store_id})...")
    
    try:
        # Make request through SerpApi using official client
        search = GoogleSearch(params)
        data = search.get_dict()
        
        print(f"SerpApi request completed")
        
        # Check if we got the right location
        if data.get('search_information'):
            actual_store = data['search_information'].get('location', {}).get('store_id')
            requested_store = data.get('search_parameters', {}).get('store_id')
            if actual_store:
                print(f"Returned store_id: {actual_store} (requested: {requested_store})")
        
        # SerpApi returns structured JSON data
        
        products = []
        
        # Extract products from SerpApi response
        search_results = data.get('organic_results', [])
        print(f"Found {len(search_results)} products from SerpApi")
        
        # Process each search result
        for idx, item in enumerate(search_results[:max_results]):
            print(f"\n  Processing product {idx + 1}/{min(len(search_results), max_results)}")
            
            # Extract data from SerpApi's structured response
            name = item.get('title') or item.get('name')
            
            # Extract price - SerpApi structure
            primary_offer = item.get('primary_offer', {})
            price_value = primary_offer.get('offer_price')
            if not price_value:
                price_value = item.get('price')
            
            price = f"${price_value}" if price_value else None
            
            # Price per unit
            price_per_unit_obj = item.get('price_per_unit', {})
            price_per_unit = price_per_unit_obj.get('amount') if isinstance(price_per_unit_obj, dict) else None
            
            # Image URL
            image_url = item.get('thumbnail')
            
            # Product URL
            product_url = item.get('product_page_url') or item.get('link')
            
            # Seller info
            seller = item.get('seller_name', 'Unknown')
            
            print(f"    Name: {name[:60] if name else 'NOT FOUND'}...")
            print(f"    Price: {price or 'NOT FOUND'}")
            print(f"    Seller: {seller}")
            
            # Only add valid products
            if name and price:
                product = WalmartSearchProduct(
                    name=name,
                    price=price,
                    price_per_unit=price_per_unit,
                    image_url=image_url,
                    product_url=product_url
                )
                products.append(product)
                print(f"    [ADDED] Product #{len(products)}")
            else:
                print(f"    [SKIPPED] Missing required data")
        
        # Create results object
        search_url = f"https://www.walmart.com/search?q={query.replace(' ', '+')}&stores={store_id}"
        results = WalmartSearchResults(
            query=query,
            search_url=search_url,
            products=products[:max_results],
            search_information=data.get('search_information'),
            search_metadata=data.get('search_metadata'),
            search_parameters=data.get('search_parameters')
        )
        
        return results
        
    except Exception as e:
        print(f"Error with SerpApi search: {e}")
        raise


def main():
    """Main function to test the search scraper"""
    import sys
    
    # Check if query is provided as command-line argument
    if len(sys.argv) > 1:
        search_query = sys.argv[1]
        # Output JSON only for command-line usage
        try:
            results = scrape_walmart_search(search_query, max_results=4)
            # Output JSON to stdout for Node.js to parse
            results_dict = results.model_dump(mode='python')
            print(json.dumps(results_dict, ensure_ascii=False))
            return 0
        except Exception as e:
            print(json.dumps({"error": str(e), "products": []}), file=sys.stderr)
            return 1
    else:
        # Default test behavior
        search_query = "Pepperidge Farm Bread, Sourdough"
        
        try:
            # Scrape search results
            results = scrape_walmart_search(search_query, max_results=4)
            
            # Display results
            print("\n" + "="*60)
            print("WALMART SEARCH RESULTS")
            print("="*60)
            print(f"Query: {results.query}")
            print(f"Search URL: {results.search_url}")
            print(f"\nFound {len(results.products)} products:")
            print("="*60)
            
            for i, product in enumerate(results.products, 1):
                print(f"\nProduct {i}:")
                print(f"  Name: {product.name or 'Not found'}")
                print(f"  Price: {product.price or 'Not found'}")
                print(f"  Price per unit: {product.price_per_unit or 'Not found'}")
                print(f"  Image URL: {product.image_url or 'Not found'}")
                print(f"  Product URL: {product.product_url or 'Not found'}")
            
            print("="*60)
            
            # Save to JSON
            output_file = "walmart_search_results.json"
            with open(output_file, 'w') as f:
                # Convert to dict and ensure proper serialization
                results_dict = results.model_dump(mode='python')
                json.dump(results_dict, f, indent=2)
            print(f"\nData saved to: {output_file}")
            
        except Exception as e:
            print(f"Failed to scrape search results: {e}")
            return 1
        
        return 0


if __name__ == "__main__":
    exit(main())

