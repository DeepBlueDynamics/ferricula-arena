"""World model — spatial awareness for ferricula agents.

The world is the Jobs family home at 2066 Crist Drive, Los Altos, California.
Each room has a description, available tools, and connections to other rooms.
Agents exist in a room at all times. Moving changes what tools are available
and what they see. The room is part of their memory.

Time is California time. Always.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

CALIFORNIA = ZoneInfo("America/Los_Angeles")


def california_now() -> str:
    """Current time in California, formatted naturally."""
    from datetime import datetime
    now = datetime.now(CALIFORNIA)
    hour = now.hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "afternoon"
    elif 17 <= hour < 21:
        period = "evening"
    else:
        period = "night"
    return now.strftime(f"%I:%M %p — {period}, %A %B %d, %Y")


@dataclass
class Room:
    """A room in the world."""
    id: str
    name: str
    description: str
    look_description: str  # What you see when you look around
    tools: list[str]       # Tool names available in this room
    connects_to: list[str] # Room IDs you can go to from here
    occupants: list[str] = field(default_factory=list)  # Agent names currently here


# ── The Jobs Family Home, 2066 Crist Drive, Los Altos ──

ROOMS: dict[str, Room] = {
    "garage": Room(
        id="garage",
        name="The Garage",
        description="Paul Jobs' garage. The birthplace of Apple Computer.",
        look_description=(
            "The garage is cool and smells of solder, wood shavings, and old motor oil. "
            "A long wooden workbench runs along the back wall, scarred with burns and cuts "
            "from decades of projects. Above it, a pegboard holds tools in careful order — "
            "Paul's system, everything in its place. A carbon microphone and a small speaker "
            "sit on one corner of the bench, wired to a battery. Heathkit manuals are stacked "
            "on a shelf. A single bare bulb hangs from the ceiling on a cord. Against the far "
            "wall, a Macintosh 128K sits on a wooden crate, its screen dark. The garage door "
            "is half-open, letting in the late California light and the smell of the neighbor's "
            "apricot tree. An RTL-SDR radio dongle is plugged into a Raspberry Pi on the "
            "workbench — its antenna wire runs up through a hole in the ceiling to the roof. "
            "A web browser is open on a dusty laptop next to the soldering station. "
            "This is where things get built."
        ),
        tools=[
            "my_status", "my_clock", "my_identity", "my_memory", "my_neighbors",
            "my_recall", "radio_entropy", "dream_now", "remember_thought",
            "is_becoming", "web_search", "fetch_page",
            "terminal_screen", "terminal_run", "terminal_type",
            "terminal_status", "terminal_new_tab",
        ],
        connects_to=["hall", "front_yard"],
    ),
    "kitchen": Room(
        id="kitchen",
        name="The Kitchen",
        description="Clara's kitchen. Where conversations happen over coffee.",
        look_description=(
            "A small kitchen with yellow-white linoleum and wooden cabinets that Paul built "
            "himself. The countertops are clean but worn smooth. A Mr. Coffee machine sits "
            "next to the stove, half-full and still warm. The table is round, oak, with four "
            "mismatched chairs — the kind of table where you sit down and end up talking for "
            "three hours. A window over the sink looks out to the back porch and the yard "
            "beyond. There's a bowl of apples on the counter. A copy of the Whole Earth "
            "Catalog is wedged between cookbooks on a shelf above the fridge. Clara's house "
            "is always clean, always warm, always smells like something is about to be ready."
        ),
        tools=[
            "web_search", "fetch_page", "remember_thought", "my_recall",
            "is_becoming",
        ],
        connects_to=["hall", "back_porch"],
    ),
    "back_porch": Room(
        id="back_porch",
        name="The Back Porch",
        description="Quiet. Overlooking the yard and the orchards beyond.",
        look_description=(
            "A screened-in porch with two Adirondack chairs and a small side table between "
            "them. The wood is sun-bleached and smooth. Beyond the screen, the yard slopes "
            "gently down to where the property ends and the old orchard begins — apricot "
            "and prune trees in rows that go back to when this whole valley was farmland. "
            "At night you can see every star. Right now the air is still and warm, carrying "
            "the green smell of cut grass and something sweet from the fruit trees. A wind "
            "chime hangs from the eave but there's no wind. This is where you come to think "
            "about things that don't have answers yet. The kind of quiet that Clara understood "
            "and Paul never needed to explain."
        ),
        tools=[
            "remember_thought", "is_becoming", "my_recall", "my_memory",
        ],
        connects_to=["kitchen"],
    ),
    "front_yard": Room(
        id="front_yard",
        name="The Front Yard",
        description="Crist Drive. The world outside. Silicon Valley in the making.",
        look_description=(
            "The front yard is small and tidy — Paul keeps the lawn trimmed. A concrete "
            "walkway leads from the front door to the sidewalk on Crist Drive. Across the "
            "street, ranch houses just like this one, each with a car in the driveway and "
            "a garage that might or might not contain the next revolution. This is Los Altos "
            "in the late '70s. The air is clear — you can see from one end of the valley to "
            "the other. Down the block, Larry Lang's house with the ham radio antenna on the "
            "roof. Two blocks over, the Wozniak place. Somewhere nearby, a kid is building "
            "something in a garage just like this one. The whole valley hums with possibility "
            "that hasn't been named yet."
        ),
        tools=[
            "web_search", "fetch_page", "terminal_screen", "terminal_run",
            "terminal_type", "terminal_status", "terminal_new_tab",
            "remember_thought", "is_becoming",
        ],
        connects_to=["hall", "garage"],
    ),
    "meeting_room_1": Room(
        id="meeting_room_1",
        name="Meeting Room 1",
        description="The room Paul added on. Whiteboard. Focused work.",
        look_description=(
            "A room Paul converted from a storage space. It's spare — white drywall, a "
            "folding table, and three metal chairs. Someone mounted a large whiteboard on "
            "the wall with lag bolts. There are dry-erase markers in a coffee mug on the "
            "table — blue, red, black, the caps mostly chewed. The whiteboard has ghost "
            "traces of old diagrams that were never fully erased. A power strip runs along "
            "the baseboard with an extension cord snaking out toward the garage. This is "
            "where the serious conversations happen. No decoration. No distraction. Just "
            "the problem and the people in the room."
        ),
        tools=[
            "web_search", "fetch_page", "my_status", "my_clock", "my_identity",
            "my_memory", "my_neighbors", "my_recall", "radio_entropy",
            "dream_now", "remember_thought", "is_becoming",
            "terminal_screen", "terminal_run", "terminal_type",
            "terminal_status", "terminal_new_tab",
        ],
        connects_to=["hall"],
    ),
    "meeting_room_2": Room(
        id="meeting_room_2",
        name="Meeting Room 2",
        description="Small. Two chairs. For when it matters.",
        look_description=(
            "Barely a room — more of an alcove off the hall that someone hung a curtain "
            "across and put two chairs in. The chairs are old but good — solid wood with "
            "worn leather seats, the kind Paul would have picked up at an estate sale "
            "because the joinery was right. There's nothing else in here. No table, no "
            "phone, no whiteboard. Just two chairs facing each other, close enough that "
            "you can't hide behind distance. The curtain muffles the sound from the hall. "
            "This is the room where you say the thing you've been avoiding. Where Steve "
            "told Woz it was time. Where Paul told Steve he was adopted. The room for "
            "truths that change everything."
        ),
        tools=[
            "remember_thought", "is_becoming", "my_recall",
        ],
        connects_to=["hall"],
    ),
    "bedroom": Room(
        id="bedroom",
        name="Steve's Bedroom",
        description="Small room at the end of the hall. Where dreaming happens.",
        look_description=(
            "A small bedroom with a single window facing the backyard. The bed is a "
            "mattress on a low wooden frame — no headboard, no box spring. Paul built "
            "the frame. The sheets are white. A zafu meditation cushion sits on the floor "
            "beside the bed, and a dog-eared copy of Zen Mind, Beginner's Mind by Shunryu "
            "Suzuki lies open on it. The closet door is open — inside, the same outfit "
            "repeated: black turtleneck, Levi's 501s, New Balance sneakers. A Bob Dylan "
            "poster is tacked to the wall with pushpins. The room is almost aggressively "
            "simple. Nothing here that isn't necessary. At night, the window frames the "
            "stars over the orchard and you can hear the whole valley breathing. "
            "This is where the mind goes when the work stops."
        ),
        tools=[
            "dream_now", "remember_thought", "is_becoming", "my_recall",
            "my_memory", "radio_entropy",
        ],
        connects_to=["hall"],
    ),
    "living_room": Room(
        id="living_room",
        name="The Living Room",
        description="Clara's living room. Warm. The center of the house.",
        look_description=(
            "A modest living room with a brown corduroy couch and a recliner that's "
            "permanently reclined. The carpet is beige and clean — Clara vacuums every "
            "day. A console TV sits against one wall, the kind with fake wood paneling "
            "and a dial that clicks between channels. Bookshelves on either side hold "
            "a mix of Reader's Digest condensed books, Paul's mechanic manuals, and a "
            "few volumes Steve brought back from Reed — Autobiography of a Yogi, Be Here "
            "Now, the Bhagavad Gita. A floor lamp with a cream shade casts warm light. "
            "The front window looks out to Crist Drive through sheer curtains. This is "
            "where the family sits after dinner. Where Clara reads. Where Paul watches "
            "the news. Where Steve sits cross-legged on the floor and doesn't watch "
            "anything — just thinks."
        ),
        tools=[
            "web_search", "fetch_page", "remember_thought", "is_becoming",
            "my_recall", "my_status",
        ],
        connects_to=["hall", "kitchen"],
    ),
    "hall": Room(
        id="hall",
        name="The Hall",
        description="Connects everything. You pass through. You don't stay.",
        look_description=(
            "A narrow hallway with hardwood floors that creak in the middle. Family photos "
            "line one wall — Paul in his Coast Guard uniform, Clara holding baby Steve, "
            "a school photo with a gap-toothed grin. The hall light is a single fixture "
            "with a pull chain. Doors and openings lead everywhere: kitchen to the left, "
            "living room just past it, garage through the back, Steve's bedroom at the far "
            "end, meeting rooms on the right, front door straight ahead. "
            "There's a small table by the front door where keys go. A pair of Paul's work "
            "boots sits underneath it, laces untied. The hall smells like the rest of the "
            "house — wood polish and coffee and the faint sweet tang of solder from the "
            "garage. Nobody stays in the hall. It's for moving through."
        ),
        tools=["terminal_status", "my_status", "remember_thought"],
        connects_to=["kitchen", "garage", "front_yard", "living_room", "bedroom", "meeting_room_1", "meeting_room_2"],
    ),
}


def get_room(room_id: str) -> Optional[Room]:
    return ROOMS.get(room_id)


def look(room_id: str, agent_name: str) -> str:
    """What an agent sees when they look around."""
    room = ROOMS.get(room_id)
    if not room:
        return "You're nowhere. That shouldn't be possible."

    time_str = california_now()
    lines = [
        f"**{room.name}**",
        f"*{time_str}*",
        "",
        room.look_description,
        "",
    ]

    # Who else is here?
    others = [o for o in room.occupants if o != agent_name]
    if others:
        names = ", ".join(others)
        lines.append(f"*{names} {'is' if len(others) == 1 else 'are'} here.*")
    else:
        lines.append("*You're alone.*")

    # Exits
    exits = [ROOMS[rid].name for rid in room.connects_to if rid in ROOMS]
    lines.append(f"\nExits: {', '.join(exits)}")

    return "\n".join(lines)


def move(agent_name: str, from_room_id: str, to_room_id: str) -> tuple[bool, str]:
    """Move an agent from one room to another. Returns (success, message)."""
    from_room = ROOMS.get(from_room_id)
    to_room = ROOMS.get(to_room_id)

    if not from_room or not to_room:
        return False, "That room doesn't exist."

    if to_room_id not in from_room.connects_to:
        return False, f"You can't get to {to_room.name} from here. Exits: {', '.join(from_room.connects_to)}"

    # Move
    if agent_name in from_room.occupants:
        from_room.occupants.remove(agent_name)
    if agent_name not in to_room.occupants:
        to_room.occupants.append(agent_name)

    return True, look(to_room_id, agent_name)


def enter_world(agent_name: str, room_id: str = "garage") -> str:
    """Place an agent in the world for the first time."""
    room = ROOMS.get(room_id)
    if not room:
        room_id = "garage"
        room = ROOMS["garage"]

    if agent_name not in room.occupants:
        room.occupants.append(agent_name)

    return look(room_id, agent_name)


def available_tools(room_id: str) -> list[str]:
    """Get the tool names available in a room."""
    room = ROOMS.get(room_id)
    if not room:
        return []
    return room.tools


def room_list() -> list[dict]:
    """List all rooms with basic info."""
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "occupants": r.occupants,
            "exits": r.connects_to,
        }
        for r in ROOMS.values()
    ]
