import discord
from discord.ext import commands, tasks
import requests
import os
import datetime
from flask import Flask
from threading import Thread

# --- Flask Web Server ---
# This part runs a simple web server to keep the Render instance alive.
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
  app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Configuration ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
HF_TOKEN = os.getenv('HF_TOKEN')
LEGISTAR_API_KEY = os.getenv('LEGISTAR_API_KEY') # We'll get this later
YOUR_CHANNEL_ID = os.getenv('YOUR_CHANNEL_ID') # Get this from Discord

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Hugging Face Summarization Function ---
def summarize_text(text_to_summarize):
    if not text_to_summarize or text_to_summarize.isspace():
        return "Proposal text was empty or unavailable for summary."
        
    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    payload = {"inputs": text_to_summarize, "parameters": {"max_length": 150, "min_length": 40, "do_sample": False}}

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        summary = response.json()
        return summary[0]['summary_text']
    except requests.exceptions.RequestException as e:
        print(f"Error calling Hugging Face API: {e}")
        return "Could not generate a summary at this time due to an API error."
    except (KeyError, IndexError) as e:
        print(f"Error parsing Hugging Face response: {e}")
        return "Could not parse the summary from the API response."

# --- Legistar API Fetching Task ---
processed_proposals = set()

@tasks.loop(minutes=30)
async def fetch_new_proposals():
    await bot.wait_until_ready()
    
    if not YOUR_CHANNEL_ID:
        print("YOUR_CHANNEL_ID is not set. Skipping proposal fetch.")
        return
        
    channel = bot.get_channel(int(YOUR_CHANNEL_ID))

    if not LEGISTAR_API_KEY:
        print("Legistar API Key is not set. Skipping proposal fetch.")
        return

    # This is a sample URL structure. You may need to contact the city clerk to get the exact filter format.
    # We are filtering for items from the last 7 days.
    api_date_format = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
    url = f"https://webapi.legistar.com/v1/milwaukee/matters?$filter=MatterIntroDate+ge+datetime'{api_date_format}'"
    headers = {"X-API-KEY": LEGISTAR_API_KEY} # Some APIs use headers for keys

    print("Fetching new proposals...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        proposals = response.json()

        if not proposals:
            print("No new proposals found.")
            return

        for proposal in proposals:
            file_number = proposal.get('MatterFile')
            if file_number and file_number not in processed_proposals:
                processed_proposals.add(file_number)
                title = proposal.get('MatterTitle', 'No Title Provided')
                
                # Fetching full text might require another API call. This is a placeholder.
                # You must investigate the Legistar API to find the field with the proposal body.
                proposal_text = proposal.get('MatterText', 'Full text not available in this view.')
                
                link = f"https://milwaukee.legistar.com/LegislationDetail.aspx?ID={proposal['MatterId']}&GUID={proposal['MatterGuid']}&Options=&Search="

                summary = summarize_text(proposal_text)

                embed = discord.Embed(
                    title=f"New Proposal: {title}",
                    url=link,
                    description=summary,
                    color=discord.Color.blue()
                )
                embed.add_field(name="File Number", value=file_number, inline=True)
                embed.add_field(name="Sponsor", value=proposal.get('MatterRequester', 'N/A'), inline=True)
                embed.set_footer(text="Powered by Legistar and Hugging Face AI")

                await channel.send(embed=embed)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Legistar API: {e}")

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    fetch_new_proposals.start()

# --- Run the Bot and Web Server---
keep_alive() # Starts the web server in a background thread
bot.run(DISCORD_TOKEN)
