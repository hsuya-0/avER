import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncio
import time
import math
from keep_alive import keep_alive

# ==========================================
#               CONFIGURATION
# ==========================================
BOT_TOKEN = "MTQ3NjU0MDY4NDUyNDcxNjEzMw.G5uJul.YDU-vSqHc_hEPb7Oi8dv23YPT7Rcl8qU8lLG24"

# Logic Configuration
ROBUX_PER_INVITE = 20
MIN_ACCOUNT_AGE_DAYS = 90
VERIFIED_ROLE_ID = 1476541346402533488
INVITE_TRACKER_CHANNEL_LINK = "https://discord.com/channels/1437713453950439436/1476541470554062928"
MIN_VALID_INVITES = 5  

# Technical Configuration 
FALCON_BOT_ID = None 
TRACKER_HISTORY_LIMIT = 5000 

# Visual Configuration
EMBED_COLOR = 0x7251c1FD700

# ==========================================
#             CUSTOM EMOJIS
# ==========================================
E_TICK = "<:check:1476876258406170716>"
E_UNTICK = "<:ex:1476876209345265684>"
E_ALERT = "<:alert:1476882380512825344>"
E_ROBUX = "<:robux:1476881623721971786>"
E_USERS = "<:users:1476882701733593118>"
E_USER = "<:user:1476882019261878282>"
E_REFRESH = "<:refresh:1476883571296960635>"
E_QUES = "<:ques:1476894828318167040>"
E_TIMEOUT = "<:timeout:1476894297654825097>"
E_FILTER = "<:blue_filter:1477242457128439851>"

# Pagination Emojis
E_PREV_PAGE = "<:lastpage:1476902904140136593>"
E_NEXT_PAGE = "<:nextpage:1476902793024508066>"

# Scanning Phase Emojis
E_PLAY = "<:neon_play_button:1477235120070201417>"
E_SEARCH = "<:search:1477234680012210277>"

# Custom Holographic Letters spelling "DASHBOARD"
E_DASHBOARD = (
    "<:holo_letter_D:1476874728542310620>"
    "<:holo_letter_a:1476874277411356803>"
    "<:holo_letter_S:1476874903104782480>"
    "<:holo_letter_H:1476891482328666206>"
    "<:holo_letter_b:1476874973548118026>"
    "<:holo_letter_O:1476875040703250442>"
    "<:holo_letter_a:1476874277411356803>"
    "<:holo_letter_R:1476891389789737081>"
    "<:holo_letter_D:1476874728542310620>"
)


class InviteValidatorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Logged in as {self.user} | Slash commands synced.")

bot = InviteValidatorBot()


# Helper function to extract IDs
def get_ids_from_msg(msg):
    text = msg.content
    for embed in msg.embeds:
        if embed.description: text += f" {embed.description}"
        for field in embed.fields: text += f" {field.name} {field.value}"
    return set(re.findall(r'<@!?(\d+)>', text))


# ==========================================
#          SCANNING PHASE UI VIEW
# ==========================================
class ScanningView(discord.ui.View):
    def __init__(self, finish_event):
        super().__init__(timeout=180) 
        self.finish_event = finish_event

    @discord.ui.button(label="Generate Dashboard", style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(E_PLAY))
    async def finish_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.finish_event.set() 


# ==========================================
#          MODERN DASHBOARD UI VIEW
# ==========================================
class ValidationDashboard(discord.ui.View):
    def __init__(self, target_user, processed_users, mention_counts, guild):
        super().__init__(timeout=900) 
        self.target_user = target_user
        self.processed_users = processed_users
        self.mention_counts = mention_counts
        self.guild = guild
        self.current_filter = "all" 
        self.current_page = 0
        self.items_per_page = 25 

    async def re_evaluate_users(self):
        """Re-checks all users in case they just got the verified role"""
        now = discord.utils.utcnow()
        for user_data in self.processed_users:
            uid = user_data['id']
            
            # Deep fetch
            member = self.guild.get_member(uid)
            if not member:
                try:
                    member = await self.guild.fetch_member(uid)
                except discord.NotFound:
                    member = None
            
            is_valid = True
            reasons =[]

            if not member:
                reasons.append("Left")
                is_valid = False
            else:
                if (now - member.created_at).days < MIN_ACCOUNT_AGE_DAYS:
                    reasons.append("New")
                    is_valid = False
                
                if not any(r.id == int(VERIFIED_ROLE_ID) for r in member.roles):
                    reasons.append("Unverified")
                    is_valid = False
                    
                if self.mention_counts.get(str(uid), 0) > 1:
                    reasons.append("Rejoined")
                    is_valid = False

            user_data['valid'] = is_valid
            user_data['reasons'] = reasons

    async def generate_embed(self):
        results =[]
        valid_count = 0
        invalid_count = 0

        for user_data in self.processed_users:
            uid = user_data['id']
            is_valid = user_data['valid']
            reasons = user_data['reasons']

            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1

            if self.current_filter == "valid" and not is_valid: continue
            if self.current_filter == "invalid" and is_valid: continue

            idx = len(results) + 1
            if is_valid:
                results.append(f"> {E_TICK} **`#{idx:02}`** • <@{uid}>")
            else:
                reason_str = ", ".join(reasons)
                results.append(f"> {E_UNTICK} **`#{idx:02}`** • <@{uid}> ⤏ `{reason_str}`")

        total_pages = max(1, math.ceil(len(results) / self.items_per_page))
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = results[start_idx:end_idx]

        description_list = "\n".join(page_items)
        if not description_list:
            description_list = f">{E_FILTER} `No users match this filter.`"

        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page >= total_pages - 1)

        eligibility_notice = ""
        if valid_count < MIN_VALID_INVITES:
            robux_total = 0
            eligibility_notice = f"\n> {E_QUES} **Not eligible:** Needs `{MIN_VALID_INVITES}` valid invites."
        else:
            robux_total = valid_count * ROBUX_PER_INVITE

        page_indicator = f" (Page {self.current_page + 1}/{total_pages})" if total_pages > 1 else ""

        final_description = (
            f"# {E_DASHBOARD}\n"
            f"Welcome to the interactive panel for {self.target_user.mention}.\n\n"
            f"### {E_USERS} Invited Members{page_indicator}\n"
            f"{description_list}\n\n"
            f"## {E_ROBUX} Redeemable: R$ {robux_total}{eligibility_notice}\n"
            f"> {E_TICK} Valid: `{valid_count}` | {E_UNTICK} Invalid: `{invalid_count}`\n\n"
            f"-# {E_REFRESH} Last refreshed: <t:{int(time.time())}:R> • To fetch brand new invites, run /validate again."
        )

        embed = discord.Embed(description=final_description, color=EMBED_COLOR)
        if self.target_user.display_avatar:
            embed.set_thumbnail(url=self.target_user.display_avatar.url)
            
        embed.set_footer(text="Made by wayush0 • v1.8")
        return embed

    @discord.ui.select(
        placeholder="Filter member list...",
        row=0,
        options=[
            discord.SelectOption(label="Show All Invites", value="all", emoji=discord.PartialEmoji.from_str(E_USERS)),
            discord.SelectOption(label="Show Valid Only", value="valid", emoji=discord.PartialEmoji.from_str(E_TICK)),
            discord.SelectOption(label="Show Invalid Only", value="invalid", emoji=discord.PartialEmoji.from_str(E_UNTICK)),
        ]
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_filter = select.values[0]
        self.current_page = 0  
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(E_PREV_PAGE), row=1)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji=discord.PartialEmoji.from_str(E_REFRESH), row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.re_evaluate_users() 
        await interaction.message.edit(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(E_NEXT_PAGE), row=1)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji=discord.PartialEmoji.from_str(E_UNTICK), row=1)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


# ==========================================
#               COMMAND LOGIC
# ==========================================
@bot.tree.command(name="validate", description="Validate invites for a user and calculate Robux")
@app_commands.describe(user="The member to validate invites for")
async def validate_invites(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()

    command_to_type = f"-invited <@{user.id}>"

    wait_embed = discord.Embed(
        description=(
            f"# {E_ALERT} Action Required\n"
            f"Please trigger the Falcon bot using this command:\n\n"
            f"```text\n{command_to_type}\n```\n"
            f"-# 💻 **On PC:** Hover over the black box above and click 'Copy'.\n"
            f"-# 📱 **On Mobile:** Type `-invited @username` manually (Discord will autocomplete).\n"
            f"-# {E_TIMEOUT} Waiting for Falcon bot response..."
        ),
        color=EMBED_COLOR
    )
    wait_embed.set_footer(text="Made by wayush0 • v1.8")
    waiting_msg = await interaction.followup.send(embed=wait_embed)

    def check_falcon_msg(m):
        if m.channel.id != interaction.channel.id: return False
        if not m.author.bot: return False
        if FALCON_BOT_ID and m.author.id != FALCON_BOT_ID: return False
        
        if m.embeds and m.embeds[0].title and "Invited list" in m.embeds[0].title: 
            return True
        if "has no invites" in m.content.lower():
            return True
            
        return False

    try:
        falcon_msg = await bot.wait_for('message', check=check_falcon_msg, timeout=60.0)
    except asyncio.TimeoutError:
        err_embed = discord.Embed(description=f"# {E_TIMEOUT} Timeout\nFalcon bot did not respond in time.\n\n-# Please run `/validate` again.", color=0xff4747)
        err_embed.set_footer(text="Made by wayush0 • v1.8")
        return await waiting_msg.edit(content=None, embed=err_embed)

    if "has no invites" in falcon_msg.content.lower():
        empty_embed = discord.Embed(
            description=f"# {E_QUES} No Invites\n{user.mention} currently has **0** invites.", 
            color=0xff4747
        )
        empty_embed.set_footer(text="Made by wayush0 • v1.8")
        return await waiting_msg.edit(content=None, embed=empty_embed)

    extracted_ids = get_ids_from_msg(falcon_msg)
    if str(user.id) in extracted_ids: extracted_ids.remove(str(user.id))

    # ==========================================
    #       PHASE 2: LIVE SCANNING MODE 
    # ==========================================
    finish_event = asyncio.Event()
    scan_view = ScanningView(finish_event)

    def generate_scan_embed():
        emb = discord.Embed(
            description=(
                f"# {E_SEARCH} Scanning Invites...\n"
                f"I have successfully read **{len(extracted_ids)}** unique invites so far.\n\n"
                f"**Does Falcon bot have multiple pages?**\n"
                f"> If yes, click the `➡️ Next` button on Falcon's message right now! I will automatically scan the new pages.\n\n"
                f"-# Automatically generating dashboard in 10 seconds..."
            ),
            color=EMBED_COLOR
        )
        emb.set_footer(text="Made by wayush0 • v1.8")
        return emb

    await waiting_msg.edit(embed=generate_scan_embed(), view=scan_view)

    while not finish_event.is_set():
        edit_task = asyncio.create_task(bot.wait_for('message_edit', check=lambda b, a: a.id == falcon_msg.id))
        event_task = asyncio.create_task(finish_event.wait())
        
        # 12-second timer to auto-proceed
        done, pending = await asyncio.wait([edit_task, event_task], return_when=asyncio.FIRST_COMPLETED, timeout=12.0)
        
        for task in pending: task.cancel()
            
        if event_task in done:
            break
        elif edit_task in done:
            try:
                before, after = edit_task.result()
                new_ids = get_ids_from_msg(after)
                old_len = len(extracted_ids)
                extracted_ids.update(new_ids)
                if str(user.id) in extracted_ids: extracted_ids.remove(str(user.id))
                
                if len(extracted_ids) > old_len:
                    await waiting_msg.edit(embed=generate_scan_embed())
            except:
                pass
        else:
            break

    if not extracted_ids:
        empty_embed = discord.Embed(description=f"# {E_QUES} No Invites\nNo valid user mentions were found in Falcon bot's response.", color=0xff4747)
        empty_embed.set_footer(text="Made by wayush0 • v1.8")
        return await waiting_msg.edit(content=None, embed=empty_embed, view=None)

    # ==========================================
    #       PHASE 3: ANALYZING TRACKER
    # ==========================================
    loading_embed = discord.Embed(description=f"# {E_SEARCH} Analyzing Data...\nFetching members, verifying roles, and checking tracker logs. Please wait...", color=EMBED_COLOR)
    loading_embed.set_footer(text="Made by wayush0 • v1.8")
    await waiting_msg.edit(embed=loading_embed, view=None)

    mention_counts = {uid: 0 for uid in extracted_ids}
    tracker_channel = None

    match = re.search(r'channels/\d+/(\d+)', INVITE_TRACKER_CHANNEL_LINK)
    if match:
        tracker_channel = interaction.guild.get_channel(int(match.group(1)))

    if tracker_channel:
        async for msg in tracker_channel.history(limit=TRACKER_HISTORY_LIMIT):
            msg_text = msg.content
            for embed in msg.embeds:
                if embed.description: msg_text += f" {embed.description}"
            msg_ids = set(re.findall(r'<@!?(\d+)>', msg_text))
            for uid_str in msg_ids:
                if uid_str in mention_counts: mention_counts[uid_str] += 1

    # ==========================================
    #       PHASE 4: PRE-PROCESSING DATA
    # ==========================================
    processed_users =[]
    now = discord.utils.utcnow()

    for uid_str in extracted_ids:
        uid = int(uid_str)
        member = interaction.guild.get_member(uid)
        
        if not member:
            try:
                member = await interaction.guild.fetch_member(uid)
            except discord.NotFound:
                member = None
                
        is_valid = True
        reasons = reasons = []

        if not member:
            reasons.append("Left")
            is_valid = False
        else:
            # Check Account Age
            if (now - member.created_at).days < MIN_ACCOUNT_AGE_DAYS:
                reasons.append("New")
                is_valid = False
            
            # Check Verified Role (Using ID)
            if not any(r.id == int(VERIFIED_ROLE_ID) for r in member.roles):
                reasons.append("Unverified")
                is_valid = False
                
            # Check Rejoins
            if mention_counts.get(str(uid), 0) > 1:
                reasons.append("Rejoined")
                is_valid = False

        processed_users.append({
            'id': uid,
            'valid': is_valid,
            'reasons': reasons
        })

    # Generate the Ultimate Dashboard
    dashboard_view = ValidationDashboard(
        target_user=user, 
        processed_users=processed_users, 
        mention_counts=mention_counts, 
        guild=interaction.guild
    )
    
    initial_embed = await dashboard_view.generate_embed()
    await waiting_msg.edit(content=None, embed=initial_embed, view=dashboard_view)

if __name__ == "__main__":
    keep_alive()
    bot.run(BOT_TOKEN)