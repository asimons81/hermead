"""Test module with intentional issues for HermeAd smoke test."""
import os  # unused import

def connect(password: str) -> str:
    """Connect to the database."""
    return f"Connecting with password: {password}"

def process(data):
    """Process data - missing type annotation on return."""
    return len(data)

if __name__ == "__main__":
    db_password = "supersecret123!"  # hardcoded password
    result = connect(db_password)
    print(result)
