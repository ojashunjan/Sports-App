import random
import stripe


def update_skill_rating(player, wins, total_matches):
    """
    Dynamically updates the player's skill rating based on their win rate.
    Called after each match or when viewing player stats.
    """

    # Prevent divide-by-zero errors
    if total_matches == 0:
        return getattr(player, "skill_rating", 1000)

    win_rate = (wins / total_matches) * 100
    base_rating = getattr(player, "skill_rating", 1000)

    # Simple ELO-style adjustment
    if win_rate > 70:
        new_rating = base_rating + random.randint(20, 50)
    elif win_rate > 50:
        new_rating = base_rating + random.randint(5, 20)
    elif win_rate > 30:
        new_rating = base_rating - random.randint(5, 15)
    else:
        new_rating = base_rating - random.randint(15, 40)

    # Clamp rating between 500 and 2000
    new_rating = max(500, min(2000, new_rating))

    # Save to player if applicable
    if hasattr(player, "skill_rating"):
        player.skill_rating = new_rating

    return new_rating


def generate_ai_recommendations(player, stats=None, sport=None, win_rate=None, skill_rating=None):
    """
    Generates personalized AI-style recommendations based on player's performance metrics.
    """

    # Extract stats
    if stats and isinstance(stats, dict):
        win_rate = win_rate if win_rate is not None else stats.get("win_rate", 0)
        skill_rating = skill_rating if skill_rating is not None else stats.get("skill_rating", 0)
    else:
        if stats:
            win_rate = win_rate if win_rate is not None else getattr(stats, "win_rate", 0)
            skill_rating = skill_rating if skill_rating is not None else getattr(stats, "skill_rating", 0)

    win_rate = win_rate or 0
    skill_rating = skill_rating or 0

    tips = []

    # Win rate analysis
    if win_rate < 40:
        tips.append("Focus on fundamentals — review your gameplay to find weak decisions.")
    elif win_rate < 70:
        tips.append("Good consistency! Work on positioning and team coordination.")
    else:
        tips.append("Outstanding performance — take on tougher opponents and refine tactics.")

    # Skill rating analysis
    if skill_rating < 1000:
        tips.append("Improve core mechanics with focused drills and regular repetition.")
    elif skill_rating < 1300:
        tips.append("Add endurance and agility sessions to your weekly routine.")
    else:
        tips.append("Elite level! Fine-tune your strategic awareness and adaptability.")

    # Sport-specific context
    if sport:
        tips.append(f"As a {sport.lower()} player, tailor your drills to sport-specific techniques and decision-making patterns.")

    # Random motivation
    tips.append(random.choice([
        "Small daily improvements lead to massive long-term gains.",
        "Visualize your moves — mental practice improves execution.",
        "Consistency beats intensity. Stick to a sustainable routine.",
        "Keep tracking progress — data-driven reflection builds mastery."
    ]))

    summary = (
        f"AI Performance Summary for {player.name}:\n"
        f"- Current win rate: {win_rate:.1f}%\n"
        f"- Skill rating: {skill_rating:.0f}\n\n"
        f"Recommended Focus Areas:\n"
        + "\n".join(f"• {tip}" for tip in tips)
    )

    return summary
