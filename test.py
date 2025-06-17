from langchain_ollama import OllamaLLM

llm = OllamaLLM(model="llama3.2")  # match the model name exactly
response = llm.invoke("Say hello!")
print(response)