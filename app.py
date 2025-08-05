from dotenv import load_dotenv
load_dotenv()
import os
import tempfile
import requests
import json

from exa_py import Exa
exa_api = os.getenv("EXA_API_KEY")
exa = Exa(api_key = exa_api)

from openai import OpenAI
client = OpenAI(
    base_url = "https://api.exa.ai",
    api_key = exa_api,
)

from typing import TypedDict, List, Dict
from langgraph.graph import START, END, StateGraph

import replicate
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
replicate.Client(REPLICATE_API_KEY=REPLICATE_API_TOKEN)

def research(links, query):
    info = {}
    for i in links:
        result = str(exa.get_contents(
            [i],
            summary = {
                "query": "Retain all information but in a concise manner."
            },
            text = True
        )).split("Summary: ")
        info[i] = result[1]
    taskStub = exa.research.create_task(
    instructions = query,
    model = "exa-research",
    output_infer_schema = True
    )
    task = exa.research.poll_task(taskStub.id)
    completion = client.chat.completions.create(
        model = "exa-research",
        messages = [
            {"role": "user", "content": query}
        ],
        stream = True,
    )
    summ = ""
    for chunk in completion:
        if chunk.choices and chunk.choices[0].delta.content:
            summ += str(chunk.choices[0].delta.content, end = "", flush = True)
    return [info, Summarizer.gen(summ)]

def web_search(query):
    result = str(exa.search_and_contents(
        query,
        type = "auto",
        num_results = 5,
        summary = True
    )).split("\n")
    links = []
    summ = []
    for i in result:
        if "URL:" in i:
            links.append(i[5:])
        elif "Summary:" in i:
            summ.append(i[9:])
    summary = Summarizer.gen(" ".join(summ))
    return [links, summary]

class STTModel:
    def __init__(self):
        self.model_name = "openai/gpt-4o-mini-transcribe"
    def run(self, audio_file):
        output = replicate.run(
            self.model_name,
            input={
                #"task": "transcribe",
                "audio_file": audio_file,
                "language": "en",
                #"timestamp": "chunk",
                #"batch_size": 64,
                #"diarise_audio": False,
                "temparature": 0
            }
        )
        x = " ".join(output)
        return x
    
stt = STTModel()

class TextModel:
    def __init__(self, model_name, system_prompt):
        self.model_name = model_name
        self.system_prompt = system_prompt
    
    def gen(self, prompt):
        input = {
            "prompt": prompt,
            "system_prompt": self.system_prompt,
        }
        x = ''
        for event in replicate.stream(
            self.model_name,
            input=input
        ):
            x += str(event)
        return x
    
Summarizer = TextModel(
    "openai/o4-mini",
    "Given an amount of text, compile it into a smaller text while not losing content."
)
WebSearcher = TextModel(
    "openai/o4-mini",
    """
    You are provided with a conversation with an user.
    Based on the conversation, you are to use Web Search wisely.
    You have two available modes
    -> WS1
    -> WS2
    WS1 returns you with some relevant links and an overview.
    WS2 returns you with content from the relevant links.
     
    @ INSTRUCTIONS
    - Always use web search if it can possibly help with the output, regardless of your own knowledge.
    - Write a web search query to find the best results.
    - Always use WS1 first.
    - Do not use WS2 if WS1 returns are sufficient.
    - Use WS2 if more information is beneficial.

    If you have previously conducted any search, the results would be provided to you.
    @ OUTPUT FORMAT
    - If replying to user
    {
        "type": "reply",
        "content": "your-reply"
    }
    - If using WS1
    {
        "type": "WS1",
        "content": "your-query"
    }
    - If using WS2
    {
        "type": "WS2",
        "content": "your-query"
    }
    Your output should ALWAYS be in the above mentioned JSON templates.
    Your reply to the user can be your insights, references, information sources etc.
    Try to make it as credible and accurate as possible.
    """
)

class Search(TypedDict):
    convo: str
    response: str
    links: List[str]
    overview: str
    results: Dict[str,str]
    reply: str

def draft(state: Search):
    prompt = f"""
    @ CONVERSATION
    {state["convo"]}

    @ WEB SEARCH 1 LINKS
    {state['links']}

    @ WEB SEARCH 1 OVERVIEW
    {state['overview']}

    @ WEB SEARCH 2 RESULTS
    {state['results']}
    """
    print("\nDRAFT PROMPT: ", prompt)
    return {
        "response": WebSearcher.gen(prompt)
    }

def route(state: Search) -> str:
    print("\nROUTING: ", state["response"])
    return json.loads(state["response"])["type"]

def reply(state: Search):
    print("\nREPLY: ", state["response"])
    return {
        "reply": json.loads(state["response"])["content"]
    }

def search(state: Search):
    print("\nWS1 SEARCH: ", state["response"])
    response = json.loads(state["response"])
    query = response["content"]
    results = web_search(query)
    return {
        "overview": results[1],
        "links": results[0]
    }

def search2(state: Search):
    print("\nWS2 SEARCH: ", state["response"], state["links"])
    results = research(state["links"], json.loads(state["response"])["content"])
    return {
        "results": results[0],
        "overview": results[1]
    }

searcher_graph = StateGraph(Search)
searcher_graph.add_node("draft", draft)
searcher_graph.add_node("reply", reply)
searcher_graph.add_node("search", search)
searcher_graph.add_node("search2", search2)
searcher_graph.add_edge(START, "draft")
searcher_graph.add_conditional_edges(
    "draft",
    route,
    {
        "reply": "reply",
        "WS1": "search",
        "WS2": "search2"
    }
)
searcher_graph.add_edge("reply", END)
searcher_graph.add_edge("search", "draft")
searcher_graph.add_edge("search2", "draft")
searcher = searcher_graph.compile()

from flask import Flask, render_template, request, jsonify
app = Flask(__name__, template_folder=".", static_folder="static")

@app.route("/", methods=["GET","POST"])
def home():
    return render_template("index.html")

@app.route("/respond", methods=["GET","POST"])
def respond():
    data = request.get_json()
    messages = data['messages']
    conversation = "\n".join(f"{msg['from']}: {msg['text']}" for msg in messages)
    output = searcher.invoke({
        "convo": conversation,
        "response": "",
        "links": [],
        "overview": "",
        "results": {},
        "reply": ""
    })
    k = output['reply'].replace("\\n","<br>")
    print(k)
    return jsonify({
        "success": True,
        "message": k
    })

@app.route("/voice-to-text", methods=["GET","POST"])
def voice_to_text():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400

    audio_file = request.files['audio']
    with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_audio:
        audio_file.save(temp_audio.name)
        audio_path = temp_audio.name

    try:
        with open(audio_path, "rb") as f:
            upload_response = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f})
        
        upload_data = upload_response.json()
        file_url = upload_data['data']['url']
    except Exception as e:
        return jsonify({'error': 'Upload failed', 'details': str(e)}), 500

    
    try:
        print(file_url[:20]+"dl/"+file_url[20:])
        result = stt.run(file_url[:20]+"dl/"+file_url[20:])  
        print("RESULT: ", result)
        return jsonify({'text': result})
    except Exception as e:
        return jsonify({'error': 'STT failed', 'details': str(e)}), 500
    
if __name__ == "__main__":

    app.run(debug=True)
