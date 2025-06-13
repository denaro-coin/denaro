import uvicorn

if __name__ == "__main__":
    uvicorn.run("denaro.node.main:app", host="0.0.0.0", port=3006, reload=True)