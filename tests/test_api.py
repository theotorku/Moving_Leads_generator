import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_dependencies():
    with patch("app.routes.leads.supabase") as mock_supabase, \
         patch("app.ai.scorer.client") as mock_openai:
        
        # Mock Supabase
        mock_supabase.table.return_value.insert.return_value.execute.return_value = None
        
        # Mock OpenAI
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = '{"score": 88, "reasoning": "Test reasoning"}'
        
        # Setup async mock for chat.completions.create
        async def async_return(*args, **kwargs):
            return mock_completion
        
        mock_openai.chat.completions.create = async_return
        
        yield mock_supabase, mock_openai

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    # Assuming the index.html is served, we check if it returns some HTML content
    assert "<!DOCTYPE html>" in response.text

def test_score_lead_endpoint(mock_dependencies):
    payload = {
        "full_name": "John Doe",
        "email": "john@example.com",
        "phone": "555-1234",
        "move_date": "2023-10-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2BR",
        "budget": "5000",
        "urgency": "High"
    }
    
    # We need to mock the async behavior of the route
    # Note: TestClient handles async endpoints automatically for the request, 
    # but our mocks need to be correct.
    
    with patch("app.routes.leads.analyze_lead") as mock_analyze:
        mock_analyze.return_value = {"score": 90, "reasoning": "Mocked AI"}
        
        response = client.post("/leads/score", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "John Doe"
        assert data["score"] == 90
        assert data["reasoning"] == "Mocked AI"
