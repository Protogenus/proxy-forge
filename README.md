# ProxyForge

A FastAPI-based web application for generating Magic: The Gathering proxy cards.

## Features

- Generate proxy cards from deck lists
- Support for multiple card layouts
- PDF generation with Scryfall integration
- Web UI with responsive design

## Setup

### Prerequisites

- Python 3.8+
- pip

### Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Unix/Mac: `source venv/bin/activate`

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Run the application:
   ```bash
   uvicorn main:app --reload
   ```

The application will be available at `http://localhost:8000`

## Usage

Visit the web interface to:
- Paste deck lists
- Configure proxy card settings
- Generate and download proxy PDFs

## API

The application provides REST API endpoints for programmatic access to proxy generation.

## License

All rights reserved.
