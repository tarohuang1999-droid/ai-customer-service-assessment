
## llama.cpp

locall llama.cpp server

```bash
llama-server -m /Users/james/llm_models/clef/Clef-Flash-Q8_0.gguf --port 8090

```

local llama.cpp request sample

```sh
curl -X POST http://localhost:8090/v1/systemone \
  -H "Content-Type: application/json" \
  -d '{
    "state": "The user is asking for an immediate refund because their package arrived completely broken.",
    "questions": {
      "is_urgent": {
        "type": "noul",
        "instructions": "Is this support request high urgency?"
      },
      "department": {
        "type": "choice",
        "instructions": "Which department should handle this ticket?",
        "criteria": {
          "billing": "Handles charges, invoices, and payment issues",
          "returns": "Handles broken items, replacements, and refunds",
          "technical_support": "Handles software or product usage bugs"
        }
      }
    }
  }'
{"model":"/Users/james/llm_models/clef/Clef-Flash-Q8_0.gguf","answers":{"is_urgent":{"type":"noul","noul":0.9250678113467616},"department":{"type":"choice","choice":"returns","probabilities":{"billing":0.003727067747141613,"returns":0.9930323266914334,"technical_support":0.0032406055614248577},"confidence":0.9895484900371501}},"usage":{"input_tokens":261,"output_tokens":0}}%

```