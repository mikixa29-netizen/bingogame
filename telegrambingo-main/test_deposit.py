import requests
import json

def test_tasker_deposit():
    """
    Test script to simulate Tasker deposit confirmation.
    This simulates sending a deposit confirmation to the bot.
    """
    # Sample deposit data (modify phone and amount as needed)
    deposit_data = {
        "amount": 100.0,
        "phone": "0911234567"  # Use the phone number of a registered user
    }

    # URL where the bot is running - use the local URL first
    bot_url = "http://0.0.0.0:5000/webhook/test"

    # Send the deposit confirmation
    try:
        response = requests.post(
            bot_url,
            json=deposit_data,
            headers={"Content-Type": "application/json"}
        )
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_tasker_deposit()