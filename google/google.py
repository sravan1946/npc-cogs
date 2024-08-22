import asyncio
import functools
import json
import logging
import re
from datetime import datetime, timezone
from textwrap import shorten
from typing import Optional
from urllib.parse import quote_plus, urlencode

import aiohttp
import discord
import js2py
from bs4 import BeautifulSoup
from html2text import html2text as h2t
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_number, text_to_file
from redbot.vendored.discord.ext import menus

from .utils import ResultMenu, Source, get_card, get_query, nsfwcheck, s
from .yandex import Yandex

logger = logging.getLogger("red.google")

# TODO Add optional way to use from google search api


class Google(Yandex, commands.Cog):
    """
    A Simple google search with image support as well
    """

    __version__ = "0.0.4"
    __authors__ = ["epic guy", "ow0x", "fixator10"]

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.options = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "upgrade-insecure-requests": "1",
            "sec-ch-arch": "x86",
            "accept-encoding": "gzip, deflate",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "sec-ch-viewport-width": "1920",
            "sec-ch-bitness": "32",
            
        }
        self.link_regex = re.compile(
            r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/\/=]*(?:\.png|\.jpe?g|\.gif))"
        )
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        await self.session.close()

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Thanks Sinbad!"""
        pre_processed = super().format_help_for_context(ctx)
        authors = "Authors: " + ", ".join(self.__authors__)
        return f"{pre_processed}\n\n{authors}\nCog Version: {self.__version__}"

    @commands.group(invoke_without_command=True)
    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    async def google(self, ctx, *, query: Optional[str] = None):
        """Google search your query from Discord channel."""
        if not query:
            return await ctx.send("Please enter something to search")

        isnsfw = nsfwcheck(ctx)
        async with ctx.typing():
            response, kwargs = await self.get_result(query, nsfw=isnsfw)
            pages = []
            groups = [response[n : n + 3] for n in range(0, len(response), 3)]
            for num, group in enumerate(groups, 1):
                emb = discord.Embed(
                    title="Google Search: {}".format(
                        query[:44] + "\N{HORIZONTAL ELLIPSIS}" if len(query) > 45 else query
                    ),
                    color=await ctx.embed_color(),
                    url=kwargs["redir"],
                )
                for result in group:
                    desc = (f"{result.url}\n" if result.url else "") + f"{result.desc}"[:800]
                    emb.add_field(
                        name=f"{result.title}",
                        value=desc or "Nothing",
                        inline=False,
                    )
                emb.description = f"Page {num} of {len(groups)}"
                emb.set_footer(
                    text=f"Safe Search: {not isnsfw} | " + kwargs["stats"].replace("\n", " ")
                )
                if "thumbnail" in kwargs:
                    emb.set_thumbnail(url=kwargs["thumbnail"])

                if "image" in kwargs and num == 1:
                    emb.set_image(url=kwargs["image"])
                pages.append(emb)
        if pages:
            await ResultMenu(source=Source(pages, per_page=1)).start(ctx)
        else:
            await ctx.send("No results.")

    @google.command()
    async def autofill(self, ctx, *, query: str):
        """Responds with a list of the Google Autofill results for a particular query."""

        params = {"client": "firefox", "hl": "en", "q": query}
        async with ctx.typing():
            # This “API” is a bit of a hack; it was only meant for use by
            # Google’s own products. and hence it is undocumented.
            # Attribution: https://shreyaschand.com/blog/2013/01/03/google-autocomplete-api/
            base_url = "https://suggestqueries.google.com/complete/search"
            try:
                async with self.session.get(base_url, params=params) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    data = json.loads(await response.read())
            except asyncio.TimeoutError:
                return await ctx.send("Operation timed out.")

            if not data[1]:
                return await ctx.send("Could not find any results.")

            await ctx.send("\n".join(data[1]))

    @google.command(aliases=["books"])
    async def book(self, ctx, *, query: str):
        """Search for a book or magazine on Google Books.

        This command requires an API key. If you are the bot owner,
        you can follow instructions on below link for how to get one:
        https://gist.github.com/ow0x/53d2dbf0f753a01b7579cd8c68edbf90

        There are special keywords you can specify in the query to search in particular fields.
        You can read more on that in detail over at:
        https://developers.google.com/books/docs/v1/using#PerformingSearch
        """
        api_key = (await ctx.bot.get_shared_api_tokens("googlebooks")).get("api_key")
        if not api_key:
            return await ctx.send_help()

        async with ctx.typing():
            base_url = "https://www.googleapis.com/books/v1/volumes"
            params = {
                "apiKey": api_key,
                "q": query,
                "printType": "all",
                "maxResults": 20,
                "orderBy": "relevance",
            }
            try:
                async with self.session.get(base_url, params=params) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    data = await response.json()
            except asyncio.TimeoutError:
                return await ctx.send("Operation timed out.")

            if len(data.get("items")) == 0:
                return await ctx.send("No results.")

            pages = []
            for i, info in enumerate(data.get("items")):
                embed = discord.Embed(colour=await ctx.embed_color())
                embed.title = info.get("volumeInfo").get("title")
                embed.url = info.get("volumeInfo").get("canonicalVolumeLink")
                summary = info.get("volumeInfo").get("description", "No summary.")
                embed.description = shorten(summary, 500, placeholder="...")
                embed.set_author(
                    name="Google Books",
                    url="https://books.google.com/",
                    icon_url="https://i.imgur.com/N3oHABo.png",
                )
                if info.get("volumeInfo").get("imageLinks"):
                    embed.set_thumbnail(
                        url=info.get("volumeInfo").get("imageLinks").get("thumbnail")
                    )
                embed.add_field(
                    name="Published Date",
                    value=info.get("volumeInfo").get("publishedDate", "Unknown"),
                )
                if info.get("volumeInfo").get("authors"):
                    embed.add_field(
                        name="Authors",
                        value=", ".join(info.get("volumeInfo").get("authors")),
                    )
                embed.add_field(
                    name="Publisher",
                    value=info.get("volumeInfo").get("publisher", "Unknown"),
                )
                if info.get("volumeInfo").get("pageCount"):
                    embed.add_field(
                        name="Page Count",
                        value=humanize_number(info.get("volumeInfo").get("pageCount")),
                    )
                embed.add_field(
                    name="Web Reader Link",
                    value=f"[Click here!]({info.get('accessInfo').get('webReaderLink')})",
                )
                if info.get("volumeInfo").get("categories"):
                    embed.add_field(
                        name="Category",
                        value=", ".join(info.get("volumeInfo").get("categories")),
                    )
                if info.get("saleInfo").get("retailPrice"):
                    currency_format = (
                        f"[{info.get('saleInfo').get('retailPrice').get('amount')} "
                        f"{info.get('saleInfo').get('retailPrice').get('currencyCode')}]"
                        f"({info.get('saleInfo').get('buyLink')} 'Click to buy on Google Books!')"
                    )
                    embed.add_field(
                        name="Retail Price",
                        value=currency_format,
                    )
                epub_available = (
                    "✅" if info.get("accessInfo").get("epub").get("isAvailable") else "❌"
                )
                pdf_available = (
                    "✅" if info.get("accessInfo").get("pdf").get("isAvailable") else "❌"
                )
                if info.get("accessInfo").get("epub").get("downloadLink"):
                    epub_available += (
                        " [`Download Link`]"
                        f"({info.get('accessInfo').get('epub').get('downloadLink')})"
                    )
                if info.get("accessInfo").get("pdf").get("downloadLink"):
                    pdf_available += (
                        " [`Download Link`]"
                        f"({info.get('accessInfo').get('pdf').get('downloadLink')})"
                    )
                embed.add_field(name="EPUB available?", value=epub_available)
                embed.add_field(name="PDF available?", value=pdf_available)
                viewablility = (
                    f"{info.get('accessInfo').get('viewability').replace('_', ' ').title()}"
                )
                embed.add_field(name="Viewablility", value=viewablility)
                embed.set_footer(text=f"Page {i + 1} of {len(data.get('items'))}")
                pages.append(embed)

            if len(pages) == 1:
                await ctx.send(embed=pages[0])
            else:
                await ResultMenu(source=Source(pages, per_page=1)).start(ctx)

    @google.command()
    async def doodle(self, ctx, month: Optional[int] = None, year: Optional[int] = None):
        """Responds with Google doodles of the current month.

        Or doodles of specific month/year if `month` and `year` values are provided.
        """
        month = month or datetime.now(timezone.utc).month
        year = year or datetime.now(timezone.utc).year

        async with ctx.typing():
            base_url = f"https://www.google.com/doodles/json/{year}/{month}"
            try:
                async with self.session.get(base_url) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    output = await response.json()
            except asyncio.TimeoutError:
                return await ctx.send("Operation timed out.")

            if not output:
                return await ctx.send("Could not find any results.")

            pages = []
            for data in output:
                em = discord.Embed(colour=await ctx.embed_color())
                em.title = data.get("title", "Doodle title missing")
                img_url = data.get("high_res_url")
                if img_url and not img_url.startswith("https:"):
                    img_url = "https:" + data.get("high_res_url")
                if not img_url:
                    img_url = "https:" + data.get("url")
                em.set_image(url=img_url)
                date = "-".join(str(x) for x in data.get("run_date_array")[::-1])
                em.set_footer(text=f"{data.get('share_text')}\nDoodle published on: {date}")
                pages.append(em)

        if len(pages) == 1:
            return await ctx.send(embed=pages[0])
        else:
            await ResultMenu(source=Source(pages, per_page=1)).start(ctx)

    @google.command(aliases=["img"])
    async def image(self, ctx, *, query: Optional[str] = None):
        """Search google images from discord"""
        if not query:
            await ctx.send("Please enter some image name to search")
        else:
            isnsfw = nsfwcheck(ctx)
            async with ctx.typing():
                response, kwargs = await self.get_result(query, images=True, nsfw=isnsfw)
                size = len(response)

                class ImgSource(menus.ListPageSource):
                    async def format_page(self, menu, page):
                        return (
                            discord.Embed(
                                title=f"Pages: {menu.current_page+1}/{size}",
                                color=await ctx.embed_color(),
                                description="Some images might not be visible.",
                                url=kwargs["redir"],
                            )
                            .set_image(url=page)
                            .set_footer(text=f"Safe Search: {not isnsfw}")
                        )

            if size > 0:
                await ResultMenu(source=ImgSource(response, per_page=1)).start(ctx)
            else:
                await ctx.send("No result")

    @google.command(aliases=["rev"], enabled=True)
    async def reverse(self, ctx, *, url: Optional[str] = None):
        """Attach or paste the url of an image to reverse search, or reply to a message which has the image/embed with the image"""
        isnsfw = nsfwcheck(ctx)
        if query := get_query(ctx, url):
            pass
        else:
            return await ctx.send_help()

        encoded = {
            "url": query,
        }
        final_url = "http://lens.google.com/uploadbyurl?" + urlencode(encoded)
        async with ctx.typing():
            async with self.session.get(
                final_url,
                headers=self.options,
            ) as resp:
                text = await resp.read()
                redir_url = resp.url
            prep = functools.partial(self.reverse_search, text)
            results = await self.bot.loop.run_in_executor(None, prep)
            pages = []
            if results:
                for num, res in enumerate(results, 1):
                    emb = discord.Embed(
                        title="Google Reverse Image Search",
                        description=f"[`{res['domain_name']}`]({res['orig_url']})",
                        color=await ctx.embed_color(),
                    )
                    # TODO maybe constraint, clip this to 1024
                    emb.add_field(
                        name=res["title"],
                        value=res["orig_url"],
                        inline=False,
                    )
                    emb.set_footer(text=f"Page: {num}/{len(results)}")
                    emb.set_thumbnail(url=res["icon_url"])
                    emb.set_image(url=res["image_url"])
                    pages.append(emb)
            if pages:
                await ResultMenu(source=Source(pages, per_page=1)).start(ctx)
            else:
                await ctx.send(
                    embed=discord.Embed(
                        title="Google Reverse Image Search",
                        description="[`" + ("Nothing significant found") + f"`]({redir_url})",
                        color=await ctx.embed_color(),
                    ).set_thumbnail(url=encoded["url"])
                )

    @commands.is_owner()
    @google.command(hidden=True)
    async def debug(self, ctx, url: str):
        async with self.session.get(url, headers=self.options) as resp:
            text = await resp.text()
        raw_html = BeautifulSoup(text, "html.parser")
        data = raw_html.prettify()
        await ctx.send(file=text_to_file(data, filename="google_debug.html"))

    async def get_result(self, query, images=False, nsfw=False):
        """Fetch the data"""
        # TODO make this fetching a little better
        encoded = quote_plus(query, encoding="utf-8", errors="replace")

        async def get_html(url, encoded):
            async with self.session.get(url + encoded, headers=self.options) as resp:
                return await resp.text(), resp.url

        if not nsfw:
            encoded += "&safe=active"

        # TYSM fixator, for the non-js query url
        url = (
            "https://www.google.com/search?tbm=isch&q="
            if images
            else "https://www.google.com/search?q="
        )
        text, redir = await get_html(url, encoded)
        prep = functools.partial(self.parser_image if images else self.parser_text, text)

        fin, kwargs = await self.bot.loop.run_in_executor(None, prep)
        kwargs["redir"] = redir
        return fin, kwargs

    def reverse_search(self, text):
        soup = BeautifulSoup(text, features="html.parser")
        all_scripts = soup.findAll("script", {"nonce": True})
        txts = []
        for tag in all_scripts:
            txt = tag.get_text()
            if txt.startswith("AF_initDataCallback("):
                txts.append(txt)

        fin_data = []
        for txt in txts:
            if "https://encrypted-tbn" in txt:
                txt = txt.replace("AF_initDataCallback", "var result = JSON.stringify", 1)
                context = js2py.EvalJs()
                context.execute(txt)
                data = json.loads(context.result)
                for item in data["data"][1][0][1][8][8][0][12]:
                    try:
                        fin_data.append(
                            {
                                "title": item[3],
                                "orig_url": item[5],
                                "domain_name": item[14],
                                "image_url": item[0][0],
                                "icon_url": item[15][0],
                            }
                        )
                    except IndexError as e:
                        # Silently ignore this for now
                        logger.debug(e)
        return fin_data

    def parser_text(self, text, soup=None, cards: bool = True):
        """My bad logic for scraping"""
        if not soup:
            soup = BeautifulSoup(text, features="html.parser")

        final = []
        kwargs = {"stats": h2t(str(soup.find("div", id="result-stats")))}

        if cards:
            get_card(soup, final, kwargs)

        for res in soup.select("div.g.tF2Cxc"):
            if name := res.find("div", class_="yuRUbf"):
                url = name.a["href"]
                if title := name.find("h3", class_=re.compile("LC20lb")):
                    title = title.text
                else:
                    title = url
            else:
                url = None
                title = None
            if desc := res.select_one("div.kb0PBd>div.VwiC3b"):
                desc = h2t(desc.text)[:500]
            else:
                desc = "Not found"
            if title:
                final.append(s(url, title, desc.replace("\n", " ")))
        return final, kwargs

    def parser_image(self, html):
        excluded_domains = (
            "google.com",
            "gstatic.com",
        )
        links = self.link_regex.findall(html)
        ind = 0
        count = 0
        while count <= 10:  # first 10 should be enough for the google icons
            for remove in excluded_domains:
                if not links:
                    return [], {}
                if remove in links[ind]:
                    links.pop(ind)
                    break
            else:
                ind += 1
            count += 1
        return links, {}
