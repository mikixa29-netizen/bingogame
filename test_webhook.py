import requests
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_webhooks():
    """
    Test script to test webhook endpoints with both Tasker and GitHub formats
    """
    # Test URLs - try both local and production
    urls = [
        "http://0.0.0.0:5000",  # Local development
        "https://bingoblaster.addisumelke01.repl.co",  # Production
    ]

    # Test data for different formats
    test_cases = [
        {
            "name": "Tasker Format",
            "data": {
                "amount": 100.0,
                "phone": "0911234567"
            },
            "headers": {
                "Content-Type": "application/json"
            }
        },
        {
            "name": "GitHub Issue Format",
            "data": {
                "issue": {
                    "title": "Deposit: 100 - 0911234567",
                    "body": "Automated deposit notification"
                }
            },
            "headers": {
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "test-delivery-id"
            }
        },
        {
            "name": "GitHub Ping",
            "data": {
                "zen": "Testing is good",
                "hook_id": "test-hook"
            },
            "headers": {
                "Content-Type": "application/json",
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "test-delivery-id"
            }
        }
    ]

    for base_url in urls:
        logger.info(f"\nTesting with base URL: {base_url}")

        for test_case in test_cases:
            logger.info(f"\nTesting {test_case['name']}...")

            # 1. Test the validation endpoint
            try:
                response = requests.post(
                    f"{base_url}/webhook/test",
                    json=test_case['data'],
                    headers=test_case['headers'],
                    timeout=10
                )
                print(f"\n{test_case['name']} Response:")
                print(json.dumps(response.json(), indent=2))

                if response.status_code == 200:
                    logger.info("✅ Test successful!")
                else:
                    logger.error(f"❌ Test failed with status code: {response.status_code}")

            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Connection error: {e}")
                continue

            # 2. If not a ping event, test the deposit endpoint
            if test_case['headers'].get('X-GitHub-Event') != 'ping':
                try:
                    response = requests.post(
                        f"{base_url}/webhook/deposit",
                        json=test_case['data'],
                        headers=test_case['headers'],
                        timeout=10
                    )
                    print("\nDeposit Endpoint Response:")
                    print(json.dumps(response.json(), indent=2))

                    if response.status_code == 200:
                        logger.info("✅ Deposit test successful!")
                    else:
                        logger.error(f"❌ Deposit test failed with status code: {response.status_code}")

                except requests.exceptions.RequestException as e:
                    logger.error(f"❌ Connection error for deposit test: {e}")
                    continue

if __name__ == "__main__":
    test_webhooks()