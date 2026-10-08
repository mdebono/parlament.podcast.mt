from parlament import app, cache

try:
    app.run()
finally:
    cache.print_colos()
