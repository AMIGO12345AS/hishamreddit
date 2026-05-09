from reddit.scraper import scrape_subreddits
from db.writer import update_post_filter_scores, update_post_insight, mark_insight_processed, mark_posts_in_history
from db.reader import get_top_insights_from_today, get_post_parent_mapping
from db.schema import create_tables
from db.cleaner import clean_old_entries
from gpt.filters import run_filter
from gpt.insights import run_insight
from scheduler.cost_tracker import initialize_cost_tracking
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import ensure_directory_exists, sanitize_text

log = setup_logger()
config = get_config()


def is_valid_post(post: dict) -> bool:
    return bool(sanitize_text(post.get("title", "")) and sanitize_text(post.get("body", "")))


def run_daily_pipeline():
    log.info("\U0001F680 Starting Reddit scraping and analysis pipeline")

    ai_cfg = config["ai"]
    log.info(f"AI provider : {ai_cfg.get('base_url')}")
    log.info(f"Filter model: {ai_cfg.get('model_filter')}")
    log.info(f"Deep model  : {ai_cfg.get('model_deep')}")

    ensure_directory_exists("data")
    create_tables()
    initialize_cost_tracking()

    log.info("Step 1: Cleaning old database entries...")
    clean_old_entries()

    log.info("Step 2: Scraping Reddit posts...")
    scraped_posts = scrape_subreddits()
    if not scraped_posts:
        log.warning("No posts found. Exiting.")
        return

    scraped_posts = [p for p in scraped_posts if is_valid_post(p)]
    log.info(f"{len(scraped_posts)} valid posts after sanitization.")
    if not scraped_posts:
        return

    weights = config["scoring"]
    score_threshold = weights.get("score_threshold", 6.0)

    # ── Phase 1: emotional filter ──────────────────────────────────────────
    log.info(f"Step 3: Phase 1 — filtering {len(scraped_posts)} posts "
             f"(model={ai_cfg.get('model_filter')}, threshold={score_threshold})...")
    scored: dict[str, tuple] = {}
    below_threshold_ids: list[str] = []

    for i, post in enumerate(scraped_posts, 1):
        log.info(f"  [{i}/{len(scraped_posts)}] Filtering {post['id']} — {post['title'][:60]}")
        try:
            scores = run_filter(post)
            if not scores:
                continue
            update_post_filter_scores(post["id"], scores)

            weighted_score = (
                scores.get("relevance_score", 0)         * weights["relevance_weight"] +
                scores.get("emotional_intensity", 0)      * weights["emotion_weight"] +
                scores.get("pain_point_clarity", 0)       * weights["pain_point_weight"] +
                scores.get("relatability_score", 0)       * weights.get("relatability_weight", 0.20) +
                scores.get("content_potential_score", 0)  * weights.get("content_potential_weight", 0.15)
            )
            log.debug(f"    scores={scores} | weighted={weighted_score:.2f}")

            if weighted_score >= score_threshold:
                scored[post["id"]] = (post, weighted_score)
            else:
                below_threshold_ids.append(post["id"])

        except Exception as e:
            log.error(f"  ❌ Filter failed for {post['id']} ({post['title'][:50]}): "
                      f"{type(e).__name__}: {e}")
            below_threshold_ids.append(post["id"])

    if below_threshold_ids:
        mark_posts_in_history(below_threshold_ids)
        log.info(f"Marked {len(below_threshold_ids)} below-threshold posts in history.")

    # Deduplicate: keep best-scoring post per thread
    parent_mapping = get_post_parent_mapping(set(scored.keys()))
    thread_best: dict[str, tuple] = {}
    for post_id, (post, score) in scored.items():
        thread_id = parent_mapping.get(post_id) or post_id
        if thread_id not in thread_best or score > thread_best[thread_id][1]:
            thread_best[thread_id] = (post, score)

    high_potential = [post for post, _ in thread_best.values()]
    log.info(f"Step 4: {len(high_potential)} high-potential posts after dedup "
             f"(threshold={score_threshold}).")

    if not high_potential:
        log.info("No high-value posts. Exiting pipeline.")
        return

    # ── Phase 2: deep content intelligence ────────────────────────────────
    log.info(f"Step 5: Phase 2 — deep analysis of {len(high_potential)} posts "
             f"(model={ai_cfg.get('model_deep')})...")
    insight_completed_ids: list[str] = []

    for i, post in enumerate(high_potential, 1):
        log.info(f"  [{i}/{len(high_potential)}] Analysing {post['id']} — {post['title'][:60]}")
        try:
            insight = run_insight(post)
            if not insight:
                continue
            update_post_insight(post["id"], insight)
            mark_insight_processed(post["id"])
            insight_completed_ids.append(post["id"])
        except Exception as e:
            log.error(f"  ❌ Insight failed for {post['id']} ({post['title'][:50]}): "
                      f"{type(e).__name__}: {e}")

    if insight_completed_ids:
        mark_posts_in_history(insight_completed_ids)
        log.info(f"Marked {len(insight_completed_ids)} insight-completed posts in history.")

    # ── Results ───────────────────────────────────────────────────────────
    output_limit = config["scoring"]["output_top_n"]
    top_posts = get_top_insights_from_today(limit=output_limit)
    log.info(f"✅ Pipeline finished. Found {len(top_posts)} content intelligence leads.")

    for i, post in enumerate(top_posts[:5], 1):
        log.info(
            f"{i}. [{post['subreddit']}] {post['title']} "
            f"— Pain: {post['roi_weight']} | Topic: {post['tags']} "
            f"| Hook: {post.get('viral_hook', 'N/A')} - {post['url']}"
        )


if __name__ == "__main__":
    run_daily_pipeline()
