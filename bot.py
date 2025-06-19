import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import os
import datetime
from flask import Flask
from threading import Thread

# --- Flask Web Server (Keeps the bot alive on Render) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
  app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Configuration (from Render Environment Variables) ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
HF_TOKEN = os.getenv('HF_TOKEN')
YOUR_CHANNEL_ID = os.getenv('YOUR_CHANNEL_ID')

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Hugging Face Summarization Function ---
def summarize_text(text_to_summarize):
    if not text_to_summarize or text_to_summarize.isspace():
        return "Proposal title was empty or unavailable for summary."
        
    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    payload = {"inputs": text_to_summarize, "parameters": {"max_length": 100, "min_length": 25, "do_sample": False}}

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        summary = response.json()
        # The summary is now of the title, so we present it as such.
        return f"AI-Generated Summary of Title:\n> {summary[0]['summary_text']}"
    except requests.exceptions.RequestException as e:
        print(f"Error calling Hugging Face API: {e}")
        return "Could not generate a summary at this time due to an API error."
    except (KeyError, IndexError) as e:
        print(f"Error parsing Hugging Face response: {e}")
        return "Could not parse the summary from the API response."

# --- Web Scraper Task ---
processed_proposal_urls = set()

@tasks.loop(minutes=30)
async def fetch_new_proposals_from_website():
    await bot.wait_until_ready()
    
    if not YOUR_CHANNEL_ID:
        print("YOUR_CHANNEL_ID is not set. Skipping proposal fetch.")
        return
        
    channel = bot.get_channel(int(YOUR_CHANNEL_ID))
    
    # The URL for the legislation page, filtered to show recent items.
    # This helps limit how much we need to scrape.
    URL = "https://milwaukee.legistar.com/Legislation.aspx?TimeFrame=Last%202%20Weeks"
    headers = {'User-Agent': 'Milwaukee Proposal Bot/1.0; +https://github.com/your-repo'}

    print("Scraping website for new proposals...")
    try:
        response = requests.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Use BeautifulSoup to parse the website's HTML
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find the main table holding all the legislative items.
        # We find this by looking for the ID 'ctl00_ContentPlaceHolder1_gridLegislation_ctl00'.
        # This ID could change if the website is updated.
        proposal_table = soup.find('table', id=lambda x: x and 'gridLegislation' in x)
        if not proposal_table:
            print("Could not find the proposal table on the page. The website structure may have changed.")
            return

        # Find all the rows in the table, skipping the header row.
        rows = proposal_table.find_all('tr', class_=['Row', 'AltRow'])
        
        for row in reversed(rows): # Reverse to post oldest new items first
            cells = row.find_all('td')
            if len(cells) > 2: # Ensure it's a valid data row
                
                # Extract the link from the 'File #' column
                link_tag = cells[0].find('a')
                if not link_tag or not link_tag.has_attr('href'):
                    continue

                proposal_url = f"https://milwaukee.legistar.com/{link_tag['href']}"
                
                if proposal_url not in processed_proposal_urls:
                    processed_proposal_urls.add(proposal_url)
                    
                    file_number = link_tag.text.strip()
                    proposal_title = cells[2].text.strip()
                    
                    print(f"Found new proposal: {file_number} - {proposal_title}")

                    # Since getting the full text is complex, we will summarize the title.
                    summary = summarize_text(proposal_title)

                    embed = discord.Embed(
                        title=f"New Proposal: {proposal_title}",
                        url=proposal_url,
                        description=summary,
                        color=discord.Color.green() # Changed color to signify scraper source
                    )
                    embed.add_field(name="File Number", value=file_number, inline=True)
                    embed.add_field(name="Status", value=cells[4].text.strip(), inline=True)
                    embed.set_footer(text="Sourced via Web Scraper | Accuracy may vary.")

                    await channel.send(embed=embed)
                    
    except requests.exceptions.RequestException as e:
        print(f"Error scraping Legistar website: {e}")

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    fetch_new_proposals_from_website.start()

# --- Run the Bot and Web Server---
keep_alive()
bot.run(DISCORD_TOKEN)
