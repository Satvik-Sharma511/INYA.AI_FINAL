📌 Overview

This project implements an Inya AI Agent Chain for managing Service Requests and Installations in the consumer durables sector.

The agent is designed to:

🔍 Detect intent (Service Request or Installation)

❓ Ask appliance-specific questions

📝 Collect and validate customer details (name, phone, email, address, pincode, preferred time)

🌐 Use a pincode-to-region API with fallback mapping

👩‍🔧 Match & schedule technicians based on skills, appliance, and region

📞 Escalate gracefully to a live agent if required

Tone: Supportive, calm, solution-oriented.

🔗 API Integration
Pincode Lookup API

Endpoint:

https://api.zippopotam.us/IN/{PINCODE}


Parsing Rule: Extract "place name" or "state" as region_label.

Fallback Mapping (regions.json)
{
  "regions": [
    {"pincode_prefix": "560011", "region_label": "Bengaluru Urban"},
    {"pincode_prefix": "400011", "region_label": "Mumbai Suburban"},
    {"pincode_prefix": "110011", "region_label": "Delhi"}
  ]
}

📂 Mock Data Files
technicians.json
{
  "technicians": [
    {
      "id": "tech_01",
      "name": "Asha K",
      "skills": ["wm_vibration", "ac_leak"],
      "appliances_supported": ["WashingMachine", "AC"],
      "regions": ["Bengaluru Urban"],
      "availability_slots": [
        {"start": "2025-09-14T10:00:00+05:30", "end": "2025-09-14T12:00:00+05:30"},
        {"start": "2025-09-14T15:00:00+05:30", "end": "2025-09-14T16:00:00+05:30"}
      ]
    }
  ]
}

regions.json


▶️ How to Run

Open the Inya Agent link provided for this project. https://app.inya.ai/chat-demo/2104941d-4c08-4050-bd2e-9a02ef3b754f

Test with different pincodes:

✅ Available technician regions:

560011 → Bengaluru Urban

400011 → Mumbai Suburban

110011 → Delhi
https://vimeo.com/1121277952?share=copy

ℹ️ Other valid pincodes:
Agent identifies region, but shows no technician availability.   https://vimeo.com/1121523502

❌ Invalid pincodes:
Agent retries API → falls back to cached mapping → returns “Not Found.”
