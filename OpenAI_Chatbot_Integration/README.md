# DVC Course Assistant - Flask Web App

A modern, user-friendly web interface for the DVC Course Assistant chatbot. This Flask application provides an intuitive chat interface to help students find STEM courses, sections, instructors, and prerequisites at Diablo Valley College.

## Features

✨ **Modern UI/UX**: Beautiful gradient design with smooth animations and responsive layout  
🤖 **AI-Powered**: Uses OpenAI GPT-4o-mini for intelligent query parsing and response formatting  
📊 **Real-time Search**: Instant course lookups from comprehensive DVC STEM database  
🔍 **Smart Filtering**: Filter by format (online/in-person/hybrid), day, time, status, and instructor  
📝 **Automatic Logging**: All user interactions are logged for analysis  
💬 **Chat Interface**: Familiar chat-based UI with example queries  

## Project Structure

```
OpenAI_Chatbot_Integration/
├── app.py                  # Flask backend with API routes
├── requirements.txt        # Python dependencies
├── user_log.json          # User interaction logs
├── templates/
│   └── index.html         # Main HTML template
└── static/
    ├── style.css          # Modern CSS styling
    └── script.js          # Frontend JavaScript
```

## Prerequisites

- Python 3.8 or higher
- OpenAI API key
- DVC course database (`Full_STEM_DataBase.json`)

## Installation

1. **Clone/Navigate to the project directory**
   ```bash
   cd /Users/savirwangoo/Desktop/course-database/OpenAI_Chatbot_Integration
   ```

2. **Create and activate a virtual environment** (recommended)
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   
   Create a `.env` file in the `OpenAI_Chatbot_Integration` directory:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   ```

5. **Verify database location**
   
   Ensure the course database exists at:
   ```
   /Users/savirwangoo/Desktop/course-database/dvc_scraper/Full_STEM_DataBase.json
   ```

## Running the Application

1. **Start the Flask server**
   ```bash
   python app.py
   ```

2. **Open your browser**
   
   Navigate to: `http://127.0.0.1:5000`

3. **Start chatting!**
   
   Try example queries like:
   - "Show me open COMSC-110 sections"
   - "What are the prerequisites for MATH-193?"
   - "Find online PHYS classes"
   - "Show MATH classes on Monday mornings"

## API Endpoints

### `GET /`
Returns the main HTML page with the chat interface.

### `POST /ask`
Main chatbot endpoint.

**Request:**
```json
{
  "query": "Show me open COMSC-110 sections"
}
```

**Response:**
```json
{
  "success": true,
  "response": "Found 3 sections for COMSC-110..."
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error message"
}
```

### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "courses_loaded": 123
}
```

## Features Breakdown

### Backend (Flask)
- RESTful API with JSON responses
- Integration with OpenAI API for NLP
- Course database querying and filtering
- Automatic interaction logging
- Error handling and validation

### Frontend
- Responsive design (mobile-friendly)
- Real-time chat interface
- Markdown rendering for formatted responses
- Auto-resizing textarea
- Loading indicators
- Example query buttons
- Keyboard shortcuts (Enter to send, Shift+Enter for new line)

### Chatbot Capabilities
- **Course Search**: Find courses by code or subject
- **Prerequisites**: Get prerequisite information
- **Instructor Lookup**: Find who teaches specific courses
- **Filtering**: By format, status, day, time, instructor
- **Typo Correction**: Handles common misspellings
- **Smart Parsing**: Understands natural language queries

## Logging

All user interactions are automatically logged to `user_log.json` with:
- Timestamp
- User prompt
- Parsed query data
- Assistant response

This data can be used for:
- Usage analytics
- Query pattern analysis
- Improving the chatbot
- Understanding user needs

## Troubleshooting

### Port Already in Use
If port 5000 is already in use, modify the port in `app.py`:
```python
app.run(debug=True, host='127.0.0.1', port=5001)  # Change port number
```

### Database Not Found
Ensure the path to `Full_STEM_DataBase.json` is correct in `app.py`:
```python
db_path = Path(__file__).parent.parent / "dvc_scraper" / "Full_STEM_DataBase.json"
```

### OpenAI API Errors
- Check your API key is valid
- Verify you have credits available
- Check your internet connection

## Development

To run in development mode with auto-reload:
```bash
export FLASK_ENV=development  # On Windows: set FLASK_ENV=development
python app.py
```

## Production Deployment

For production deployment, consider:
- Using a production WSGI server (Gunicorn, uWSGI)
- Setting up HTTPS
- Configuring environment variables securely
- Adding rate limiting
- Implementing user authentication if needed

Example with Gunicorn:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Technologies Used

- **Backend**: Flask (Python)
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **AI/ML**: OpenAI GPT-4o-mini
- **Styling**: Custom CSS with modern design patterns
- **Markdown**: Marked.js for rendering formatted responses

## Contributing

To add new features or improve the chatbot:
1. Modify the query parsing logic in `llm_parse_query()`
2. Update filtering logic in `search_courses()`
3. Enhance response formatting in the LLM system prompt
4. Add new Flask routes in `app.py`
5. Extend frontend features in `script.js` and `style.css`

## License

Educational project for DVC students.

## Support

For issues or questions:
- Check the troubleshooting section
- Review the console logs (browser and terminal)
- Verify all prerequisites are met

---

**Happy Course Searching! 🎓**

