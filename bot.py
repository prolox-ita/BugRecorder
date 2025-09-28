# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

import discord
from discord.ext import commands, tasks

# =========================
#        CONFIG
# =========================
# 👉 Aggiorna questi ID in base al tuo server
TARGET_CHANNEL_ID = 1420493501984149585   # canale di destinazione per i report/todo
ALLOWED_CHANNEL_ID = 1280758855336464426  # canale autorizzato per usare i comandi (!bug, !crash, !todo, !status)
EXPORT_CHANNEL_ID = 1420493501984149585   # canale dove postare l'export pin

# =========================
#     ENV / TOKEN CHECK
# =========================
load_dotenv()
token = os.getenv("DISCORD_TOKEN")
if not token:
    print("ERRORE: DISCORD_TOKEN non trovato nelle variabili d'ambiente!")
    print("Configura il token Discord nei Secrets del progetto.")
    sys.exit(1)

# =========================
#        LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("discord.log", encoding="utf-8", mode="w"),
        logging.FileHandler("uptime.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# =========================
#   VARIABILI GLOBALI
# =========================
bot_start_time: datetime = datetime.now()
last_heartbeat: datetime = datetime.now()
disconnection_count: int = 0
reconnection_attempts: int = 0

REPORT_COUNTER: int = 1
classified_reports = {}  # report_id -> dict
export_message_id = None

# Stato temporaneo durante la compilazione:
# _active_reports[author_id] = {
#   "arr": [display_name, version, date, category, subcategory, description],
#   "report_type": "Bug"|"Crash"|"Todo",
#   "origin_channel_id": int,
#   "report_id": int,
#   "message_ts": datetime
# }
_active_reports = {}

# Metadati per bottoni priorità:
# _report_meta[report_message_id] = {
#   "report_type": "Bug"|"Crash"|"Todo",
#   "origin_channel_id": int,
#   "author_id": int,
#   "report_id": int
# }
_report_meta = {}

# =========================
#        DISCORD BOT
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # abilita "Server Members Intent" nel Developer Portal

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
#         EVENTS
# =========================
@bot.event
async def on_ready():
    global last_heartbeat, bot_start_time
    bot_start_time = datetime.now()
    last_heartbeat = datetime.now()

    logger.info(f"🟢 Bot online: {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"🔗 Connesso a {len(bot.guilds)} server")
    logger.info(f"⏱️ Avvio completato alle: {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"We are ready to go!, {bot.user.name}")

    if not uptime_monitor.is_running():
        uptime_monitor.start()

    # 👉 avvio ping orario canale report
    if not channel_keepalive_pinger.is_running():
        channel_keepalive_pinger.start()


@bot.event
async def on_disconnect():
    global disconnection_count
    disconnection_count += 1
    logger.warning(f"🔴 Bot disconnesso! (Disconnessione #{disconnection_count})")


@bot.event
async def on_resumed():
    global last_heartbeat
    last_heartbeat = datetime.now()
    logger.info(f"🟡 Bot riconnesso alle: {last_heartbeat.strftime('%Y-%m-%d %H:%M:%S')}")


# =========================
#     UPTIME MONITOR
# =========================
@tasks.loop(minutes=5)
async def uptime_monitor():
    global last_heartbeat
    try:
        current_time = datetime.now()
        last_heartbeat = current_time

        uptime = current_time - bot_start_time
        uptime_hours = uptime.total_seconds() / 3600
        latency_ms = round(bot.latency * 1000, 2) if bot.latency else 0

        logger.info(
            f"💓 Heartbeat: Uptime={uptime_hours:.1f}h, Latency={latency_ms}ms, Guilds={len(bot.guilds)}"
        )

        if latency_ms > 5000:
            logger.warning(f"⚠️ Latenza alta rilevata: {latency_ms}ms")

    except Exception as e:
        logger.error(f"❌ Errore nel monitoraggio uptime: {e}")


@uptime_monitor.before_loop
async def before_uptime_monitor():
    await bot.wait_until_ready()


# =========================
#   HOURLY CHANNEL PING
# =========================
@tasks.loop(minutes=60)
async def channel_keepalive_pinger():
    """Invia un messaggio ogni ora nel canale dei report."""
    try:
        ch = bot.get_channel(TARGET_CHANNEL_ID)
        if not ch:
            logger.error(f"❌ Canale target {TARGET_CHANNEL_ID} non trovato per keep-alive ping")
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await ch.send(f"⏰ Hourly ping — still alive ({now})")
        logger.info("📣 Keep-alive ping inviato nel canale dei report.")
    except discord.Forbidden:
        logger.warning("⚠️ Permessi mancanti per scrivere nel canale keep-alive.")
    except Exception as e:
        logger.error(f"❌ Errore nel keep-alive ping: {e}")


@channel_keepalive_pinger.before_loop
async def before_channel_keepalive_pinger():
    await bot.wait_until_ready()


# =========================
#        COMMANDS
# =========================
@bot.command()
async def status(ctx: commands.Context):
    """Mostra lo stato e le statistiche del bot."""
    try:
        current_time = datetime.now()
        uptime = current_time - bot_start_time

        embed = discord.Embed(
            title="📊 Stato Bot",
            color=discord.Color.green(),
            timestamp=current_time,
        )

        # uptime breakdown
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        embed.add_field(name="⏱️ Uptime", value=f"{days}d {hours}h {minutes}m {seconds}s", inline=True)

        latency_ms = round(bot.latency * 1000, 2) if bot.latency else 0
        embed.add_field(name="🏓 Latenza", value=f"{latency_ms}ms", inline=True)

        embed.add_field(name="🌐 Server", value=f"{len(bot.guilds)}", inline=True)

        embed.add_field(
            name="📈 Statistiche",
            value=f"Disconnessioni: {disconnection_count}\nRiconnessioni: {reconnection_attempts}",
            inline=False,
        )

        await ctx.reply(embed=embed, mention_author=False)

    except Exception as e:
        logger.error(f"Errore comando status: {e}")
        await ctx.reply("❌ Errore nel recuperare le statistiche del bot.")


@bot.command()
async def bug(ctx: commands.Context):
    await ctx.reply("Please, can you be more precise? Please select the category")


@bot.command()
async def crash(ctx: commands.Context):
    await ctx.reply("Oh no, that's terrible! Please, can you be more precise? Please select the category")


@bot.command()
async def todo(ctx: commands.Context):
    """Avvia il flow per creare un TODO (descrizione max 150, categoria/sottocategoria)."""
    await ctx.reply("📝 Let's add a TODO. Please select the category.")


# =========================
#     MESSAGE GATE / MOD
# =========================
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # limita i comandi (!) a un solo canale
    if message.content.startswith("!") and ALLOWED_CHANNEL_ID and message.channel.id != ALLOWED_CHANNEL_ID:
        try:
            await message.channel.send(
                f"❌ {message.author.mention} I comandi del bot sono consentiti solo in <#{ALLOWED_CHANNEL_ID}>"
            )
        except Exception:
            pass
        return

    # moderazione semplice
    if "shit" in message.content.lower():
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} don't use that word")
            logger.info(f"🛡️ Messaggio moderato da {message.author} in #{message.channel}")
        except discord.Forbidden:
            logger.warning(f"⚠️ Mancano permessi per moderare in #{message.channel}")
            try:
                await message.channel.send(f"{message.author.mention} please avoid using inappropriate language.")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"❌ Errore nella moderazione: {e}")

    await bot.process_commands(message)


# =========================
#     REPORT / EXPORT
# =========================
async def save_classified_report(report_id: int, priority: str, meta: dict, report_data: str):
    """Salva un report classificato nel database per export."""
    global classified_reports

    lines = report_data.splitlines()
    user = version = category = subcategory = date = description = ""
    report_type = meta.get("report_type", "Report")

    for line in lines:
        s = line.strip()
        if s.startswith("**User**:"):
            user = s.split(":", 1)[1].strip()
        elif s.startswith("**Version**:"):
            version = s.split(":", 1)[1].strip()
        elif s.startswith("**Category**:"):
            category = s.split(":", 1)[1].strip()
        elif s.startswith("**Sub-category**:"):
            subcategory = s.split(":", 1)[1].strip()
        elif s.startswith("**Date**:"):
            date = s.split(":", 1)[1].strip()
        elif s.startswith("**Description (optional)**:"):
            description = s.split(":", 1)[1].strip()
            if description == "—":
                description = ""

    classified_reports[report_id] = {
        "priority": priority,
        "category": category,
        "subcategory": subcategory,
        "user": user,
        "version": version,
        "date": date,
        "description": description,
        "report_type": report_type,
    }

    logger.info(f"📝 Report #{report_id} salvato con priorità {priority}")


async def generate_export_file() -> str:
    """Genera il testo export raggruppato per priorità > categoria > sottocategoria."""
    if not classified_reports:
        return "# REPORT CLASSIFICATI\n\nNessun report classificato al momento.\n"

    priority_order = ["HIGH PRIORITY", "MEDIUM PRIORITY", "LOW PRIORITY", "ALREADY SOLVED"]
    content = "# REPORTS\n"
    content += f"Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += f"Total reports: {len(classified_reports)}\n\n"

    # per priorità
    for prio in priority_order:
        prio_reports = {k: v for k, v in classified_reports.items() if v["priority"] == prio}
        if not prio_reports:
            continue

        content += f"## {prio} ({len(prio_reports)} report)\n\n"

        # raggruppa per categoria/sottocategoria
        categories = {}
        for report_id, report in prio_reports.items():
            cat = report["category"]
            sub = report["subcategory"]
            categories.setdefault(cat, {}).setdefault(sub, []).append((report_id, report))

        for cat in sorted(categories.keys()):
            content += f"### {cat}\n"
            for sub in sorted(categories[cat].keys()):
                content += f"#### {sub}\n"
                for report_id, report in sorted(categories[cat][sub]):
                    content += (
                        f"- **#{report_id}** [{report['report_type']}] "
                        f"**{report['user']}** | {report['version']} | {report['date']}"
                    )
                    if report["description"]:
                        content += f" | {report['description']}"
                    content += "\n"
                content += "\n"
            content += "\n"

        content += "---\n\n"

    return content


async def update_export_message():
    """Aggiorna (o crea) un messaggio pin con embed + file di export."""
    global export_message_id

    try:
        export_channel = bot.get_channel(EXPORT_CHANNEL_ID)
        if not export_channel:
            logger.error(f"❌ Canale export {EXPORT_CHANNEL_ID} non trovato")
            return

        file_content = await generate_export_file()

        import io
        file_buffer = io.BytesIO(file_content.encode("utf-8"))
        discord_file = discord.File(
            file_buffer, filename=f"reports_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )

        embed = discord.Embed(
            title="📊 Reports",
            description=(
                f"**Total reports**: {len(classified_reports)}\n"
                f"**Last update**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        # stats per priorità
        priority_stats = {}
        for rep in classified_reports.values():
            priority_stats[rep["priority"]] = priority_stats.get(rep["priority"], 0) + 1

        stats_text = ""
        for prio in ["HIGH PRIORITY", "MEDIUM PRIORITY", "LOW PRIORITY", "ALREADY SOLVED"]:
            count = priority_stats.get(prio, 0)
            if count > 0:
                stats_text += f"• {prio}: {count}\n"

        if stats_text:
            embed.add_field(name="📈 Statistiche per Priorità", value=stats_text, inline=False)

        # rimuovi messaggio precedente se noto
        if export_message_id:
            try:
                old = await export_channel.fetch_message(export_message_id)
                await old.delete()
            except Exception:
                pass

        sent = await export_channel.send(embed=embed, file=discord_file)
        export_message_id = sent.id

        try:
            await sent.pin()
            logger.info(f"📌 Messaggio export aggiornato e fissato (ID: {export_message_id})")
        except discord.Forbidden:
            logger.warning("⚠️ Mancano permessi per fissare il messaggio di export")
        except discord.HTTPException:
            logger.warning("⚠️ Impossibile fissare il messaggio (troppi pin?)")

    except Exception as e:
        logger.error(f"❌ Errore nell'aggiornamento del messaggio di export: {e}")


# =========================
#   PRIORITY BUTTON VIEW
# =========================
class PriorityOnReportView(discord.ui.View):
    def __init__(self, *, timeout: float = 86400):
        super().__init__(timeout=timeout)

    async def _set_priority(self, interaction: discord.Interaction, value: str):
        msg = interaction.message
        content = msg.content or ""
        lines = content.splitlines()

        # aggiorna/aggiungi riga Priority
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith("**Priority**:"):
                lines[i] = f"**Priority**: {value}"
                replaced = True
                break
        if not replaced:
            inserted = False
            for i, line in enumerate(lines):
                if line.strip().startswith("**Description"):
                    lines.insert(i, f"**Priority**: {value}")
                    inserted = True
                    break
            if not inserted:
                lines.append(f"**Priority**: {value}")

        meta = _report_meta.get(msg.id, {})
        report_type = meta.get("report_type", "Report")
        origin_channel_id = meta.get("origin_channel_id")
        author_id = meta.get("author_id")
        report_id = meta.get("report_id", 0)

        rt_lower = report_type.lower()
        if value == "ALREADY SOLVED":
            channel_notice = f"This {rt_lower} #{report_id} has been already solved."
            user_notice = (
                f"Thanks for your feedback #{report_id}, however the devs have already solved this issue "
                "and you will find this modification in the next update."
            )
            for child in self.children:
                child.disabled = True
        else:
            prio_lower = value.replace(" PRIORITY", "").lower()
            channel_notice = f"```This {rt_lower} #{report_id} has been classified as {prio_lower} priority.```"
            user_notice = (
                f"```Thanks. Your feedback #{report_id} has been registered, "
                f"for now it is classified as {prio_lower} priority.```"
            )

        await interaction.response.edit_message(content="\n".join(lines), view=self)

        try:
            await save_classified_report(report_id, value, meta, "\n".join(lines))
            await update_export_message()
            logger.info(f"📊 Export aggiornato dopo classificazione report #{report_id} ({value})")
        except Exception as e:
            logger.error(f"❌ Errore nell'aggiornamento export per report #{report_id}: {e}")

        try:
            await msg.channel.send(channel_notice)
        except Exception as e:
            logger.exception("Notifica canale report fallita: %s", e)

        try:
            if origin_channel_id and author_id:
                origin_ch = interaction.client.get_channel(origin_channel_id)
                if origin_ch:
                    await origin_ch.send(f"<@{author_id}> {user_notice}")
        except Exception as e:
            logger.exception("Notifica canale origine fallita: %s", e)

    @discord.ui.button(label="HIGH PRIORITY", style=discord.ButtonStyle.danger)
    async def btn_high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority(interaction, "HIGH PRIORITY")

    @discord.ui.button(label="MEDIUM PRIORITY", style=discord.ButtonStyle.primary)
    async def btn_medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority(interaction, "MEDIUM PRIORITY")

    @discord.ui.button(label="LOW PRIORITY", style=discord.ButtonStyle.secondary)
    async def btn_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority(interaction, "LOW PRIORITY")

    @discord.ui.button(label="ALREADY SOLVED", style=discord.ButtonStyle.success)
    async def btn_solved(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority(interaction, "ALREADY SOLVED")


# =========================
#        MODALS
# =========================
class DescriptionModal(discord.ui.Modal, title="Breve descrizione del problema"):
    def __init__(self, author_id: int):
        super().__init__()
        self.author_id = author_id
        self.desc = discord.ui.TextInput(
            label="Descrizione (max 150 caratteri)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=150,
            placeholder="Es: crash aprendo la mappa della regione X...",
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)

        state = _active_reports.pop(self.author_id, None)
        if not state:
            return await interaction.response.send_message("Sessione scaduta. Rilancia il comando.", ephemeral=True)

        arr = state["arr"]
        report_type = state["report_type"]
        origin_channel_id = state["origin_channel_id"]
        author_id = self.author_id
        report_id = state["report_id"]

        arr[5] = (str(self.desc.value).strip()) if self.desc.value else ""
        display_name, version, date_str, category, subcategory, description = arr
        icon = "🐞" if report_type == "Bug" else "💥"

        report_text = (
            f"**{report_type} #{report_id} - {category}/{subcategory} [{version}]**\n"
            f"{icon} **{report_type} Report #{report_id}**\n"
            f"**Date**: {date_str}\n"
            f"**User**: {display_name}\n"
            f"**Version**: {version}\n"
            f"**Category**: {category}\n"
            f"**Sub-category**: {subcategory}\n"
            f"**Priority**: —\n"
            f"**Description (optional)**: {description or '—'}"
        )

        target_channel = interaction.client.get_channel(TARGET_CHANNEL_ID)
        if target_channel:
            sent = await target_channel.send(report_text, view=PriorityOnReportView())
            _report_meta[sent.id] = {
                "report_type": report_type,
                "origin_channel_id": origin_channel_id,
                "author_id": author_id,
                "report_id": report_id,
            }
            await interaction.response.send_message("✅ Report inviato nel canale dedicato.", ephemeral=True)
        else:
            sent = await interaction.response.send_message(report_text, view=PriorityOnReportView(), ephemeral=False)

        if origin_channel_id:
            origin_ch = interaction.client.get_channel(origin_channel_id)
            if origin_ch:
                await origin_ch.send(report_text)


class TodoDescriptionModal(discord.ui.Modal, title="Descrizione TODO"):
    def __init__(self, author_id: int):
        super().__init__()
        self.author_id = author_id
        self.desc = discord.ui.TextInput(
            label="Cosa bisogna fare? (max 150)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=150,
            placeholder="Es: Rinominare etichetta su schermata mappe...",
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)

        state = _active_reports.pop(self.author_id, None)
        if not state:
            return await interaction.response.send_message("Sessione scaduta. Rilancia il comando.", ephemeral=True)

        arr = state["arr"]
        origin_channel_id = state["origin_channel_id"]
        author_id = self.author_id
        report_id = state["report_id"]

        # arr = [display_name, version(None), date, category, subcategory, description]
        arr[5] = str(self.desc.value).strip()
        display_name, version, date_str, category, subcategory, description = arr
        icon = "📝"
        report_type = "Todo"

        report_text = (
            f"**{report_type} #{report_id} - {category}/{subcategory}**\n"
            f"{icon} **{report_type} #{report_id}**\n"
            f"**Date**: {date_str}\n"
            f"**User**: {display_name}\n"
            f"**Version**: —\n"
            f"**Category**: {category}\n"
            f"**Sub-category**: {subcategory}\n"
            f"**Priority**: —\n"
            f"**Description (optional)**: {description or '—'}"
        )

        target_channel = interaction.client.get_channel(TARGET_CHANNEL_ID)
        if target_channel:
            sent = await target_channel.send(report_text, view=PriorityOnReportView())
            _report_meta[sent.id] = {
                "report_type": report_type,
                "origin_channel_id": origin_channel_id,
                "author_id": author_id,
                "report_id": report_id,
            }
            await interaction.response.send_message("✅ TODO inviato nel canale dedicato.", ephemeral=True)
        else:
            sent = await interaction.response.send_message(report_text, view=PriorityOnReportView(), ephemeral=False)

        if origin_channel_id:
            origin_ch = interaction.client.get_channel(origin_channel_id)
            if origin_ch:
                await origin_ch.send(report_text)


# =========================
#        VIEWS
# =========================
class SubcategoryView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout=180):
        super().__init__(timeout=180)
        self.author_id = author_id

    def add_option_buttons(self, options):
        for label in options:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

            async def callback(interaction: discord.Interaction, chosen_label=label):
                if interaction.user.id != self.author_id:
                    return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)
                state = _active_reports.get(self.author_id)
                if not state:
                    return await interaction.response.send_message("Sessione scaduta.", ephemeral=True)
                state["arr"][4] = chosen_label  # subcategory
                await interaction.response.send_modal(DescriptionModal(self.author_id))

            btn.callback = callback
            self.add_item(btn)


class CategoryView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout=180):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def _handle_category(self, interaction: discord.Interaction, category_upper: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)
        state = _active_reports.get(self.author_id)
        if not state:
            return await interaction.response.send_message("Sessione scaduta.", ephemeral=True)

        state["arr"][3] = category_upper  # category

        options_map = {
            "MAP": ["UI", "VISUAL", "MOVING", "Other"],
            "SETTLEMENTS": ["Slots", "Buildings", "Loc", "Non selectable", "Other"],
            "FACTIONS": ["Leader", "Loc", "Flags", "Other"],
            "ARMIES": ["Generals/Admirals", "Units", "Loc", "Ui", "Other"],
        }
        subview = SubcategoryView(self.author_id)
        subview.add_option_buttons(options_map[category_upper])

        await interaction.response.send_message("Please select the **sub-category**:", view=subview, ephemeral=True)

    @discord.ui.button(label="Map", style=discord.ButtonStyle.primary)
    async def btn_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "MAP")

    @discord.ui.button(label="Settlements", style=discord.ButtonStyle.secondary)
    async def btn_settlements(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "SETTLEMENTS")

    @discord.ui.button(label="Factions", style=discord.ButtonStyle.success)
    async def btn_factions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "FACTIONS")

    @discord.ui.button(label="Armies", style=discord.ButtonStyle.danger)
    async def btn_armies(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "ARMIES")


# ---- TODO Views (senza selezione versione) ----
class TodoSubcategoryView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout=180):
        super().__init__(timeout=180)
        self.author_id = author_id

    def add_option_buttons(self, options):
        for label in options:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

            async def callback(interaction: discord.Interaction, chosen_label=label):
                if interaction.user.id != self.author_id:
                    return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)
                state = _active_reports.get(self.author_id)
                if not state:
                    return await interaction.response.send_message("Sessione scaduta.", ephemeral=True)
                state["arr"][4] = chosen_label  # subcategory
                await interaction.response.send_modal(TodoDescriptionModal(self.author_id))

            btn.callback = callback
            self.add_item(btn)


class TodoCategoryView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout=180):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def _handle_category(self, interaction: discord.Interaction, category_upper: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)
        state = _active_reports.get(self.author_id)
        if not state:
            return await interaction.response.send_message("Sessione scaduta.", ephemeral=True)

        state["arr"][3] = category_upper  # category

        options_map = {
            "MAP": ["UI", "VISUAL", "MOVING", "Other"],
            "SETTLEMENTS": ["Slots", "Buildings", "Loc", "Non selectable", "Other"],
            "FACTIONS": ["Leader", "Loc", "Flags", "Other"],
            "ARMIES": ["Generals/Admirals", "Units", "Loc", "Ui", "Other"],
        }
        subview = TodoSubcategoryView(self.author_id)
        subview.add_option_buttons(options_map[category_upper])

        await interaction.response.send_message("Please select the **sub-category** for TODO:", view=subview, ephemeral=True)

    @discord.ui.button(label="Map", style=discord.ButtonStyle.primary)
    async def btn_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "MAP")

    @discord.ui.button(label="Settlements", style=discord.ButtonStyle.secondary)
    async def btn_settlements(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "SETTLEMENTS")

    @discord.ui.button(label="Factions", style=discord.ButtonStyle.success)
    async def btn_factions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "FACTIONS")

    @discord.ui.button(label="Armies", style=discord.ButtonStyle.danger)
    async def btn_armies(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_category(interaction, "ARMIES")


class VersionView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout=180):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def _handle_version(self, interaction: discord.Interaction, version: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Non sei autorizzato.", ephemeral=True)
        state = _active_reports.get(self.author_id)
        if not state:
            return await interaction.response.send_message("Sessione scaduta.", ephemeral=True)

        state["arr"][1] = version  # version
        await interaction.response.send_message(
            "Please select the **category**:", view=CategoryView(self.author_id), ephemeral=True
        )

    @discord.ui.button(label="0.0.0", style=discord.ButtonStyle.secondary)
    async def btn_v000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_version(interaction, "0.0.0")

    @discord.ui.button(label="0.0.1", style=discord.ButtonStyle.secondary)
    async def btn_v001(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_version(interaction, "0.0.1")


# =========================
#   HOOK: command flow
# =========================
@bot.event
async def on_command_completion(ctx: commands.Context):
    try:
        if ctx.command and ctx.command.name in {"bug", "crash", "todo"}:
            global REPORT_COUNTER
            _active_reports.pop(ctx.author.id, None)

            display_name = ctx.author.display_name
            ts: datetime = ctx.message.created_at
            date_str = ts.date().isoformat()

            # Assegna ID e incrementa
            report_id = REPORT_COUNTER
            REPORT_COUNTER += 1

            if ctx.command.name in {"bug", "crash"}:
                report_type = "Bug" if ctx.command.name == "bug" else "Crash"

                await ctx.send(
                    f"{ctx.author.mention} Select the **version** used (ID: #{report_id}):",
                    view=VersionView(author_id=ctx.author.id),
                )

                _active_reports[ctx.author.id] = {
                    "arr": [display_name, None, date_str, None, None, None],
                    "report_type": report_type,
                    "origin_channel_id": ctx.channel.id,
                    "report_id": report_id,
                    "message_ts": ts,
                }

            elif ctx.command.name == "todo":
                # Flow TODO: niente versione, vai direttamente a categoria -> subcategoria -> descrizione
                await ctx.send(
                    f"{ctx.author.mention} Select the **category** for TODO (ID: #{report_id}):",
                    view=TodoCategoryView(author_id=ctx.author.id),
                )

                _active_reports[ctx.author.id] = {
                    "arr": [display_name, None, date_str, None, None, None],
                    "report_type": "Todo",
                    "origin_channel_id": ctx.channel.id,
                    "report_id": report_id,
                    "message_ts": ts,
                }

    except Exception as e:
        logger.exception("Errore flow bug/crash/todo: %s", e)


# =========================
#   SHUTDOWN / MAIN LOOP
# =========================
async def shutdown_handler():
    logger.info("🔴 Arresto del bot in corso...")
    if uptime_monitor.is_running():
        uptime_monitor.cancel()
    if channel_keepalive_pinger.is_running():
        channel_keepalive_pinger.cancel()
    await bot.close()


async def main():
    global reconnection_attempts
    while True:
        try:
            logger.info("🚀 Avvio del bot Discord...")
            await bot.start(token)
        except discord.errors.ConnectionClosed:
            logger.warning("🔄 Connessione chiusa, tentativo di riconnessione...")
            reconnection_attempts += 1
            await asyncio.sleep(5)
        except discord.errors.LoginFailure:
            logger.error("❌ Errore di autenticazione! Verificare il token Discord.")
            break
        except Exception as e:
            logger.error(f"❌ Errore inaspettato: {e}")
            reconnection_attempts += 1
            await asyncio.sleep(10)

        if reconnection_attempts > 5:
            logger.error("❌ Troppi tentativi di riconnessione falliti. Arresto.")
            break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Arresto manuale del bot.")
