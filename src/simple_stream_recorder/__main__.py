"""Execution entrypoint when invoked as a directory module (python -m)."""

from simple_stream_recorder.app import create_app

def main():
    # Generate the application layout
    app = create_app()
    
    # Run server locally. Production setups typically use gunicorn or uwsgi
    app.run(host="0.0.0.0", port=5000, use_reloader=False)

if __name__ == "__main__":
    main()
