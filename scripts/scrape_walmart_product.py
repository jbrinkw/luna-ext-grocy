import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, HttpUrl
from typing import Optional
import json


class WalmartProduct(BaseModel):
    """Pydantic model for Walmart product data"""
    url: str
    title: Optional[str] = None
    price: Optional[str] = None
    price_per_unit: Optional[str] = None
    image_url: Optional[HttpUrl] = None
    


def scrape_walmart_product(product_url: str) -> WalmartProduct:
    """
    Scrape Walmart product page using scrape.do API
    
    Args:
        product_url: The Walmart product URL to scrape
        
    Returns:
        WalmartProduct: Parsed product information
    """
    # Hardcoded API key
    API_KEY = "2c78f21f63894bd8b0b16de2c53f5b6f30d8514b50d"
    
    # scrape.do API endpoint
    scrape_do_url = "http://api.scrape.do"
    
    # Parameters for scrape.do
    params = {
        "token": API_KEY,
        "url": product_url,
    }
    
    print(f"Fetching product data from: {product_url}")
    print("Using scrape.do API...")
    
    try:
        # Make request through scrape.do
        response = requests.get(scrape_do_url, params=params, timeout=60)
        response.raise_for_status()
        
        print(f"Response status: {response.status_code}")
        
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract product title
        title = None
        title_elem = soup.find('h1', {'itemprop': 'name'})
        if not title_elem:
            title_elem = soup.find('h1')
        if title_elem:
            title = title_elem.get_text(strip=True)
        
        # Extract price - try multiple selectors
        price = None
        price_per_unit = None
        
        # Try finding price by itemprop
        price_elem = soup.find('span', {'itemprop': 'price'})
        if not price_elem:
            # Try other common price selectors
            price_elem = soup.find('span', {'class': lambda x: x and 'price' in x.lower()}) if not price_elem else price_elem
        
        if price_elem:
            price = price_elem.get_text(strip=True)
        
        # Try to find price per unit
        price_unit_elem = soup.find('span', {'class': lambda x: x and 'unit' in x.lower() if x else False})
        if price_unit_elem:
            price_per_unit = price_unit_elem.get_text(strip=True)
        
        # Extract main product image
        image_url = None
        
        # First priority: Look for og:image meta tag (often has high-quality image)
        og_image = soup.find('meta', {'property': 'og:image'})
        if og_image and og_image.get('content'):
            image_url = og_image.get('content')
            print(f"Found image in og:image meta tag")
        
        # Second priority: Look for /seo/ images with .jpeg in img tags
        if not image_url:
            all_images = soup.find_all('img')
            for img in all_images:
                src = img.get('src') or img.get('data-src') or img.get('data-image-src')
                if src and '/seo/' in src and '.jpeg' in src:
                    image_url = src
                    print(f"Found image in img tag with /seo/ path")
                    break
        
        # Third priority: Look for any walmartimages.com images that are NOT icons/svgs
        if not image_url:
            for img in all_images:
                src = img.get('src') or img.get('data-src') or img.get('data-image-src')
                if src and 'i5.walmartimages.com' in src and not src.endswith('.svg'):
                    # Skip tiny icons
                    if 'icon' not in src.lower() and 'spark' not in src.lower():
                        image_url = src
                        print(f"Found image in img tag (fallback)")
                        break
        
        # Clean up image URL if needed
        if image_url and not image_url.startswith('http'):
            image_url = 'https:' + image_url if image_url.startswith('//') else 'https://www.walmart.com' + image_url
        
        # Create product object
        product = WalmartProduct(
            url=product_url,
            title=title,
            price=price,
            price_per_unit=price_per_unit,
            image_url=image_url
        )
        
        return product
        
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        raise
    except Exception as e:
        print(f"Error parsing product data: {e}")
        raise


def main():
    """Main function to test the scraper"""
    import sys
    
    # Check if URL is provided as command-line argument
    if len(sys.argv) > 1:
        walmart_url = sys.argv[1]
        # Output JSON only for command-line usage
        try:
            product = scrape_walmart_product(walmart_url)
            # Output JSON to stdout for Node.js to parse
            product_dict = product.model_dump(mode='python')
            if product_dict.get('image_url'):
                product_dict['image_url'] = str(product_dict['image_url'])
            print(json.dumps(product_dict, ensure_ascii=False))
            return 0
        except Exception as e:
            print(json.dumps({"error": str(e), "url": walmart_url}), file=sys.stderr)
            return 1
    else:
        # Default test behavior
        walmart_url = "https://www.walmart.com/ip/Banquet-Spaghetti-and-Meatballs-Frozen-Meal-10-oz-Frozen/47386166?classType=REGULAR&athbdg=L1100&from=/search"
        
        try:
            # Scrape the product
            product = scrape_walmart_product(walmart_url)
            
            # Display results
            print("\n" + "="*60)
            print("PRODUCT INFORMATION")
            print("="*60)
            print(f"Title: {product.title or 'Not found'}")
            print(f"Price: {product.price or 'Not found'}")
            print(f"Price per unit: {product.price_per_unit or 'Not found'}")
            print(f"Image URL: {product.image_url or 'Not found'}")
            print("="*60)
            
            # Save to JSON
            output_file = "walmart_product_data.json"
            with open(output_file, 'w') as f:
                # Convert to dict and ensure URLs are strings
                product_dict = product.model_dump(mode='python')
                if product_dict.get('image_url'):
                    product_dict['image_url'] = str(product_dict['image_url'])
                json.dump(product_dict, f, indent=2)
            print(f"\nData saved to: {output_file}")
            
        except Exception as e:
            print(f"Failed to scrape product: {e}")
            return 1
        
        return 0


if __name__ == "__main__":
    exit(main())

