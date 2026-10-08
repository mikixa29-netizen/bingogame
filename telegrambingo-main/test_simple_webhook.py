import requests
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_simple_webhook():
    """
    Simple test script that matches Tasker's HTTP Request format
    """
    # Test data - this matches the Tasker SMS variables
    test_data = {
        "amount": 100.0,
        "phone": "0911234567"  # Replace with actual test phone number
    }

    # Headers - same as Tasker's Content-Type setting
    headers = {
        "Content-Type": "application/json"
    }

    # The URL from your Tasker setup
    url = "https://bingoblaster.addisumelke01.repl.co/webhook/test"

    try:
        logger.info(f"Sending test request to: {url}")
        logger.info(f"Data: {test_data}")
        
        response = requests.post(
            url,
            json=test_data,
            headers=headers,
            timeout=10
        )
        
        logger.info(f"Status Code: {response.status_code}")
        logger.info("Response:")
        print(json.dumps(response.json(), indent=2))
        
        if response.status_code == 200:
            logger.info("✅ Test successful!")
        else:
            logger.error(f"❌ Test failed with status code: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    test_simple_webhook()
