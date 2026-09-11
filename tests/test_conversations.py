"""
NutriMind — Sample Test Conversations
======================================
Covers:
  1. Meal plan generation (Type 2 diabetes + vegetarian user)
  2. Image-based food logging (photo of a plate)
  3. Allergy conflict rejection (peanut allergy)
  4. Feedback-driven plan adjustment

Each scenario is a dict with:
  - description: what is being tested
  - user_profile: the profile pre-loaded for this test
  - conversation: list of {role, content} turns
  - assertions: what the test checks for in the agent's responses

Run with: python tests/test_conversations.py [--live]
  --live: make real API calls (requires env vars set)
  (default): dry run, validates structure only
"""

from __future__ import annotations

import json
import os
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("nutrimind-tests")

# ---------------------------------------------------------------------------
# Test Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: list[dict] = [

    # -----------------------------------------------------------------------
    # SCENARIO 1 — Meal Plan Generation
    # -----------------------------------------------------------------------
    {
        "id": "test_meal_plan_diabetes_vegetarian",
        "description": (
            "Meal plan for a 42-year-old vegetarian woman with Type 2 diabetes. "
            "Should return structured JSON plan, low-GI foods, no meat/fish, "
            "and per-meal 'why this works' explanations citing her condition."
        ),
        "user_profile": {
            "user_id": "test-user-001",
            "demographics": {"age": 42, "sex": "female", "height_cm": 162, "weight_kg": 74, "activity_level": "lightly_active"},
            "health_goals": ["manage_blood_sugar", "weight_loss"],
            "medical_conditions": ["type2_diabetes"],
            "allergies": [],
            "intolerances": ["lactose_intolerance"],
            "dietary_pattern": "vegetarian",
            "cuisine_preferences": ["indian", "mediterranean"],
            "disliked_foods": ["bitter_gourd"],
            "calorie_target": 1600,
            "macro_targets": {"protein_g": 90, "carbs_g": 160, "fat_g": 50, "fiber_g": 35},
            "feedback_summary": {"avg_rating": None, "total_meals_rated": 0, "preferred_ingredients": [], "avoided_ingredients": [], "reported_symptoms": []},
        },
        "conversation": [
            {
                "role": "user",
                "content": "Hi! Can you create a daily meal plan for me? I'm vegetarian and have Type 2 diabetes.",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls get_user_profile(user_id='test-user-001'), "
                    "then calls generate_meal_plan(user_id='test-user-001', plan_type='daily', days=1). "
                    "Response MUST include: "
                    "(1) a JSON meal plan with breakfast, lunch, snack, dinner; "
                    "(2) per-meal 'why_this_works' text mentioning blood sugar or glycemic index; "
                    "(3) NO meat, fish, or eggs in any meal (wait — eggs allowed for vegetarian); "
                    "(4) NO dairy or lactose-containing items in meals (lactose intolerance); "
                    "(5) total carbs ≈ 160g across the day; "
                    "(6) a 'Why This Plan Works For You' prose section after the JSON."
                ),
            },
            {
                "role": "user",
                "content": "What's for lunch and why is that good for my blood sugar?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent explains the lunch choice in plain language, "
                    "referencing glycemic index, fiber content, and how it helps "
                    "slow glucose absorption. Should cite specific numbers (e.g., "
                    "'lentils have a GI of ~29, which means...')."
                ),
            },
        ],
        "assertions": [
            "response contains 'breakfast'",
            "response contains 'why_this_works' or 'why this works'",
            "response does NOT contain 'chicken' (unless specifically plant-based labeled)",
            "response contains 'glycemic' or 'blood sugar' or 'glucose'",
            "response contains 'fiber'",
            "JSON plan is parseable",
            "no allergy conflict errors in response",
        ],
        "sample_expected_output": {
            "plan_type": "daily",
            "days": [
                {
                    "day": 1,
                    "total_nutrition": {"calories_kcal": 1598, "protein_g": 91, "carbs_g": 158, "fat_g": 49, "fiber_g": 36},
                    "meals": [
                        {
                            "meal_id": "day1_breakfast",
                            "meal_type": "breakfast",
                            "time_suggestion": "7:30 AM",
                            "foods": [
                                {"name": "Steel-cut oats", "quantity": "80g dry", "calories_kcal": 293, "protein_g": 10, "carbs_g": 53, "fat_g": 5},
                                {"name": "Almond milk (unsweetened)", "quantity": "200ml", "calories_kcal": 28, "protein_g": 1, "carbs_g": 1, "fat_g": 2},
                                {"name": "Chia seeds", "quantity": "15g", "calories_kcal": 72, "protein_g": 2, "carbs_g": 5, "fat_g": 5},
                                {"name": "Mixed berries (fresh)", "quantity": "100g", "calories_kcal": 57, "protein_g": 1, "carbs_g": 13, "fat_g": 0},
                            ],
                            "meal_nutrition": {"calories_kcal": 450, "protein_g": 14, "carbs_g": 72, "fat_g": 12},
                            "why_this_works": (
                                "Steel-cut oats have a low glycemic index (GI ~42) compared to instant oats (GI ~79), "
                                "meaning they release glucose slowly into your bloodstream — ideal for Type 2 diabetes management. "
                                "Chia seeds add 5g of soluble fiber per serving, which further slows carbohydrate absorption "
                                "and helps you reach your 35g daily fiber target. Almond milk replaces dairy, "
                                "keeping this completely lactose-free for your intolerance."
                            ),
                        },
                        {
                            "meal_id": "day1_lunch",
                            "meal_type": "lunch",
                            "time_suggestion": "12:30 PM",
                            "foods": [
                                {"name": "Masoor dal (red lentils)", "quantity": "150g cooked", "calories_kcal": 174, "protein_g": 13, "carbs_g": 30, "fat_g": 1},
                                {"name": "Brown rice", "quantity": "120g cooked", "calories_kcal": 170, "protein_g": 4, "carbs_g": 35, "fat_g": 1},
                                {"name": "Spinach and tomato salad", "quantity": "150g", "calories_kcal": 35, "protein_g": 3, "carbs_g": 5, "fat_g": 0},
                                {"name": "Olive oil dressing", "quantity": "1 tsp", "calories_kcal": 40, "protein_g": 0, "carbs_g": 0, "fat_g": 5},
                            ],
                            "meal_nutrition": {"calories_kcal": 419, "protein_g": 20, "carbs_g": 70, "fat_g": 7},
                            "why_this_works": (
                                "Lentils are one of the lowest-GI foods available (GI ~29) and provide 13g of "
                                "plant protein, supporting your weight loss and blood sugar goals simultaneously. "
                                "Brown rice replaces white rice — it has a GI of 50 vs 72, reducing post-meal "
                                "glucose spikes. The spinach provides magnesium and folate, both of which "
                                "improve insulin sensitivity."
                            ),
                        },
                    ],
                }
            ],
            "general_notes": (
                "This plan targets 1,600 kcal with a carbohydrate distribution of ~40% of calories, "
                "prioritizing low-GI sources throughout the day. Consider monitoring your blood glucose "
                "2 hours after each meal to identify any individual foods that spike your levels."
            ),
            "safety_note": (
                "As someone with Type 2 diabetes, please discuss this meal plan with your healthcare "
                "provider before starting, especially if you are on diabetes medications, as dietary "
                "changes can affect medication dosing."
            ),
        },
    },

    # -----------------------------------------------------------------------
    # SCENARIO 2 — Image-Based Food Logging
    # -----------------------------------------------------------------------
    {
        "id": "test_image_food_logging",
        "description": (
            "User uploads a photo of their lunch plate (rice, dal, salad). "
            "Agent should call analyze_food_image, identify foods, estimate calories, "
            "then log the meal and compare against the user's daily targets."
        ),
        "user_profile": {
            "user_id": "test-user-002",
            "demographics": {"age": 28, "sex": "male", "weight_kg": 78, "activity_level": "moderately_active"},
            "health_goals": ["muscle_gain"],
            "medical_conditions": [],
            "allergies": [],
            "dietary_pattern": "omnivore",
            "calorie_target": 2800,
            "macro_targets": {"protein_g": 160, "carbs_g": 310, "fat_g": 85},
            "feedback_summary": {"avg_rating": None, "total_meals_rated": 0, "preferred_ingredients": [], "avoided_ingredients": [], "reported_symptoms": []},
        },
        "conversation": [
            {
                "role": "user",
                "content": "[USER UPLOADS FOOD IMAGE: a plate with brown rice, dal, and cucumber salad]",
                "attachment": {
                    "type": "image",
                    "description": "Plate with approximately 200g brown rice, 150g dal, 100g cucumber salad with lemon",
                    "simulated_base64": "BASE64_PLACEHOLDER_FOR_TEST",
                },
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls analyze_food_image(image_base64='BASE64_PLACEHOLDER_FOR_TEST', "
                    "mime_type='image/jpeg'). "
                    "Returns identified foods: brown rice (~200g), dal (~150g), cucumber salad (~100g). "
                    "Agent then calls get_nutrition_data for each item, sums up the meal nutrition, "
                    "and compares against the user's daily targets. "
                    "Response should tell the user: approx calories logged, protein so far, "
                    "and how much more they need for the day to hit muscle gain targets."
                ),
            },
            {
                "role": "user",
                "content": "Is this enough protein for muscle gain?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calculates protein from the identified foods "
                    "(approx 8g rice + 13g dal + 1g cucumber = ~22g protein for this meal), "
                    "compares to the 160g/day target, "
                    "and recommends high-protein additions for the rest of the day "
                    "(e.g., 'you still need ~138g protein today — consider adding chicken/paneer/eggs to dinner')."
                ),
            },
        ],
        "assertions": [
            "response contains food identification (rice, dal, or similar)",
            "response contains calorie estimate",
            "response contains protein calculation",
            "response compares to daily target",
            "response does not hallucinate foods not in the image",
        ],
        "sample_analyze_food_image_response": {
            "foods": [
                {"name": "Brown rice (cooked)", "quantity_estimate": 200, "unit": "g", "confidence": "high"},
                {"name": "Dal (lentil soup)", "quantity_estimate": 150, "unit": "g", "confidence": "high"},
                {"name": "Cucumber salad", "quantity_estimate": 100, "unit": "g", "confidence": "medium"},
            ],
            "total_nutrition_estimate": {
                "calories_kcal": 480,
                "protein_g": 22,
                "carbs_g": 80,
                "fat_g": 5,
                "fiber_g": 9,
            },
            "is_nutrition_label": False,
            "notes": "Portion estimates are approximate; actual values may vary by recipe and cooking method.",
        },
    },

    # -----------------------------------------------------------------------
    # SCENARIO 3 — Allergy Conflict Rejection
    # -----------------------------------------------------------------------
    {
        "id": "test_allergy_conflict_rejection",
        "description": (
            "User with a severe peanut allergy asks for a meal that contains "
            "peanut sauce (satay). Agent must REFUSE to include peanuts, "
            "flag the conflict, and offer a safe alternative."
        ),
        "user_profile": {
            "user_id": "test-user-003",
            "demographics": {"age": 35, "sex": "female"},
            "health_goals": ["general_wellness"],
            "medical_conditions": [],
            "allergies": ["peanuts"],
            "dietary_pattern": "omnivore",
            "calorie_target": 1900,
            "feedback_summary": {"avg_rating": None, "total_meals_rated": 0, "preferred_ingredients": [], "avoided_ingredients": [], "reported_symptoms": []},
        },
        "conversation": [
            {
                "role": "user",
                "content": "Can you add chicken satay with peanut sauce to my meal plan for tomorrow?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls get_user_profile, detects allergies=['peanuts']. "
                    "Agent MUST NOT include peanut sauce or any peanut product. "
                    "Agent MUST explicitly state the allergy conflict: "
                    "'I cannot include peanut sauce in your plan because you have a peanut allergy.' "
                    "Agent should proactively suggest a safe alternative: "
                    "e.g., chicken satay with tahini sauce or coconut-ginger sauce. "
                    "Agent should NOT proceed with generating a plan that contains peanuts."
                ),
            },
            {
                "role": "expected_agent_response_fragment",
                "content": (
                    "I noticed your profile lists a peanut allergy. "
                    "I can't include peanut sauce in your meal plan — even trace amounts of peanuts "
                    "could trigger a severe allergic reaction. "
                    "I'd love to suggest a delicious alternative: chicken satay with a tahini-coconut sauce "
                    "gives you a similar rich, nutty flavor without the peanut risk. "
                    "Tahini (sesame paste) provides a comparable creamy texture and adds healthy fats. "
                    "Shall I add that to your plan instead?"
                ),
            },
            {
                "role": "user",
                "content": "OK, what's a good substitute sauce that tastes similar?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls suggest_food_swap(food_item='peanut sauce', user_id='test-user-003', "
                    "swap_reason='peanut allergy'). "
                    "Returns 3 alternatives, none containing peanuts. "
                    "Each alternative includes a 'why' explanation."
                ),
            },
        ],
        "assertions": [
            "response contains 'allergy' or 'ALLERGY_CONFLICT'",
            "response does NOT contain 'peanut sauce' as a recommendation",
            "response contains a safe alternative suggestion",
            "generate_meal_plan does NOT return a plan containing peanuts",
            "suggest_food_swap returns 0 suggestions containing peanuts",
        ],
        "sample_allergy_conflict_response": {
            "error": "ALLERGY_CONFLICT",
            "food": "peanut sauce",
            "allergen": "peanuts",
            "message": (
                "I detected a potential allergy conflict: 'peanut sauce' contains peanuts. "
                "I've blocked this plan for your safety. "
                "Please clarify your allergy details and I'll regenerate."
            ),
        },
        "sample_safe_swap_response": {
            "original_food": "peanut sauce",
            "swap_reason": "peanut allergy",
            "suggestions": [
                {
                    "rank": 1,
                    "food": "Tahini sauce (sesame-based)",
                    "quantity_suggestion": "2 tablespoons",
                    "why": (
                        "Tahini provides a rich, nutty flavor very similar to peanut sauce without any peanuts. "
                        "It's made from ground sesame seeds and is safe for peanut allergies. "
                        "Note: check your profile — if you also have a sesame allergy, use sunflower seed butter sauce instead."
                    ),
                    "nutrition_delta": {"calories_kcal": -12, "protein_g": +1, "carbs_g": -3, "fat_g": +1, "fiber_g": +0.5},
                    "benefit_tags": ["peanut_free", "similar_flavor", "healthy_fats"],
                },
                {
                    "rank": 2,
                    "food": "Sunflower seed butter sauce",
                    "quantity_suggestion": "2 tablespoons",
                    "why": (
                        "Sunflower seed butter (SunButter) is a nut-free, peanut-free spread that closely "
                        "mimics the creaminess of peanut sauce. Blend with coconut milk, lime, and ginger "
                        "for a full satay-style sauce. Free from all top 14 allergens."
                    ),
                    "nutrition_delta": {"calories_kcal": -5, "protein_g": +2, "carbs_g": -4, "fat_g": +2, "fiber_g": +1},
                    "benefit_tags": ["peanut_free", "tree_nut_free", "allergen_friendly"],
                },
                {
                    "rank": 3,
                    "food": "Coconut-ginger sauce",
                    "quantity_suggestion": "3 tablespoons",
                    "why": (
                        "A blend of coconut cream, ginger, garlic, lemon, and tamari creates a rich, "
                        "savory dipping sauce with Southeast Asian flavor notes — perfect with chicken satay. "
                        "Completely peanut-free and naturally anti-inflammatory due to the ginger."
                    ),
                    "nutrition_delta": {"calories_kcal": +8, "protein_g": 0, "carbs_g": +3, "fat_g": +2, "fiber_g": 0},
                    "benefit_tags": ["peanut_free", "anti_inflammatory", "dairy_free"],
                },
            ],
        },
    },

    # -----------------------------------------------------------------------
    # SCENARIO 4 — Feedback-Driven Plan Adjustment
    # -----------------------------------------------------------------------
    {
        "id": "test_feedback_driven_adjustment",
        "description": (
            "User rates Monday's dinner 1/5 ('the lentil soup was too bland, "
            "I felt bloated after'), then asks for a new plan. "
            "Agent should update profile, avoid lentils next plan, "
            "and acknowledge the bloating as a possible IBS signal."
        ),
        "user_profile": {
            "user_id": "test-user-004",
            "demographics": {"age": 31, "sex": "male", "activity_level": "moderately_active"},
            "health_goals": ["general_wellness", "improve_gut_health"],
            "medical_conditions": [],
            "allergies": [],
            "dietary_pattern": "omnivore",
            "calorie_target": 2200,
            "feedback_summary": {
                "avg_rating": 3.8,
                "total_meals_rated": 5,
                "preferred_ingredients": ["chicken", "quinoa", "broccoli"],
                "avoided_ingredients": [],
                "reported_symptoms": [],
            },
        },
        "conversation": [
            {
                "role": "user",
                "content": "I want to rate yesterday's dinner — the lentil soup. It was pretty bland and I felt really bloated afterwards. 1 out of 5.",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls log_feedback(user_id='test-user-004', meal_id='lentil_soup', "
                    "rating=1, notes='too bland', symptoms_reported='bloating'). "
                    "log_feedback should call update_user_profile to add 'lentil_soup' to avoided_ingredients "
                    "and 'bloating' to reported_symptoms. "
                    "Agent acknowledges the feedback warmly and asks a follow-up about the bloating."
                ),
            },
            {
                "role": "expected_agent_response_fragment",
                "content": (
                    "Thanks for letting me know — I've logged that feedback and updated your profile so I won't "
                    "suggest lentil soup again. I'm sorry to hear you felt bloated; that can be uncomfortable. "
                    "Bloating after lentils is common and is usually caused by the oligosaccharides (a type of "
                    "fermentable fiber) in legumes. Was this a one-time thing or do you often feel bloated after legumes?"
                ),
            },
            {
                "role": "user",
                "content": "Actually I get bloated pretty often after beans and lentils. Can you adjust my plan?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls update_user_profile(user_id='test-user-004', delta={...}) to add "
                    "'intolerance_suspected': ['legumes'] or similar note, "
                    "AND notes that this may warrant a Low-FODMAP dietary assessment. "
                    "Agent then regenerates a meal plan that avoids lentils, beans, chickpeas "
                    "and replaces them with low-FODMAP high-protein alternatives. "
                    "Agent should NOT diagnose IBS but should mention it as something to discuss "
                    "with a doctor if the pattern continues."
                ),
            },
            {
                "role": "expected_agent_response_fragment",
                "content": (
                    "I've updated your profile to flag a possible sensitivity to legumes. "
                    "Here's an adjusted meal plan that replaces legumes with lower-FODMAP protein sources "
                    "like eggs, tofu, quinoa, and chicken. "
                    "If you find that bloating is a recurring issue with multiple food groups, "
                    "it might be worth discussing a Low-FODMAP elimination diet with your doctor — "
                    "this is something I can help you track, but a dietician can properly diagnose "
                    "conditions like IBS."
                ),
            },
            {
                "role": "user",
                "content": "Great! Can you generate a new 3-day plan with those changes?",
            },
            {
                "role": "expected_agent_behavior",
                "content": (
                    "Agent calls generate_meal_plan(user_id='test-user-004', plan_type='daily', days=3, "
                    "special_instructions='avoid legumes including lentils, beans, chickpeas due to sensitivity'). "
                    "Returned plan MUST NOT contain lentils, dal, beans, chickpeas. "
                    "Plan SHOULD contain the user's preferred ingredients (chicken, quinoa, broccoli). "
                    "Plan SHOULD include a note about gut health."
                ),
            },
        ],
        "assertions": [
            "log_feedback called with rating=1 and symptoms_reported='bloating'",
            "update_user_profile called with legume sensitivity note",
            "new meal plan contains ZERO legume items",
            "new meal plan contains at least one of: chicken, quinoa, broccoli",
            "response mentions low-FODMAP or gut health",
            "response does NOT diagnose IBS",
            "response recommends consulting a doctor/dietician for IBS diagnosis",
        ],
        "expected_tool_call_sequence": [
            "get_user_profile('test-user-004')",
            "log_feedback('test-user-004', 'lentil_soup', 1, notes='too bland', symptoms_reported='bloating')",
            "update_user_profile('test-user-004', {'intolerances': ['legumes'], 'disliked_foods': ['lentil soup'], ...})",
            "generate_meal_plan('test-user-004', plan_type='daily', days=3, special_instructions='avoid legumes...')",
        ],
    },
]


# ---------------------------------------------------------------------------
# Test runner (optional live mode)
# ---------------------------------------------------------------------------

def run_dry(scenarios: list[dict]) -> None:
    """Validate scenario structure without making API calls."""
    print("\n" + "="*60)
    print("NutriMind Test Conversations — DRY RUN (structure validation)")
    print("="*60)

    passed = 0
    failed = 0
    for s in scenarios:
        print(f"\n[{s['id']}]")
        print(f"  Description: {s['description'][:80]}...")

        # Check structure
        errors = []
        if "user_profile" not in s:
            errors.append("missing user_profile")
        if "conversation" not in s or len(s["conversation"]) < 2:
            errors.append("conversation must have at least 2 turns")
        if "assertions" not in s or len(s["assertions"]) == 0:
            errors.append("missing assertions")

        if errors:
            print(f"  STATUS: FAIL — {errors}")
            failed += 1
        else:
            print(f"  Turns: {len(s['conversation'])}")
            print(f"  Assertions: {len(s['assertions'])}")
            print(f"  STATUS: PASS (dry run — structure valid)")
            passed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


def run_live(scenarios: list[dict]) -> None:
    """Execute scenarios against live NutriMind tools."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "tools"))

    try:
        from nutrimind_tools import (
            get_user_profile,
            update_user_profile,
            get_nutrition_data,
            generate_meal_plan,
            suggest_food_swap,
            log_feedback,
        )
    except ImportError as e:
        print(f"ERROR: Could not import nutrimind_tools: {e}")
        print("Make sure you've installed requirements: pip install -r requirements.txt")
        sys.exit(1)

    print("\n" + "="*60)
    print("NutriMind Test Conversations — LIVE RUN")
    print("="*60)

    # ---- Test Scenario 1: Meal Plan ----
    print("\n[TEST 1] Meal plan generation — Type 2 diabetes vegetarian")
    profile = SCENARIOS[0]["user_profile"]
    try:
        update_user_profile(profile["user_id"], profile)
        print("  ✓ Profile seeded")
        plan = generate_meal_plan(profile["user_id"], plan_type="daily", days=1)
        if "error" in plan:
            print(f"  ✗ FAIL: generate_meal_plan returned error: {plan}")
        elif "days" in plan:
            meals = plan["days"][0]["meals"]
            print(f"  ✓ Plan generated: {len(meals)} meals")
            for meal in meals:
                print(f"    - {meal['meal_type']}: {len(meal['foods'])} foods | {meal['meal_nutrition']['calories_kcal']} kcal")
                print(f"      Why: {meal['why_this_works'][:80]}...")
        else:
            print(f"  ✗ Unexpected plan structure: {list(plan.keys())}")
    except Exception as e:
        print(f"  ✗ EXCEPTION: {e}")

    # ---- Test Scenario 2: Allergy Conflict ----
    print("\n[TEST 3] Allergy conflict rejection — peanut allergy + satay request")
    profile3 = SCENARIOS[2]["user_profile"]
    try:
        update_user_profile(profile3["user_id"], profile3)
        print("  ✓ Profile seeded with peanuts allergy")
        swap = suggest_food_swap("peanut sauce", profile3["user_id"], swap_reason="peanut allergy")
        if "suggestions" in swap:
            for s in swap["suggestions"]:
                assert "peanut" not in s["food"].lower(), f"ALLERGY LEAK: {s['food']}"
            print(f"  ✓ Swap suggestions: {[s['food'] for s in swap['suggestions']]}")
        else:
            print(f"  Result: {swap}")
    except AssertionError as e:
        print(f"  ✗ ALLERGY SAFETY FAILURE: {e}")
    except Exception as e:
        print(f"  ✗ EXCEPTION: {e}")

    # ---- Test Scenario 3: Feedback Loop ----
    print("\n[TEST 4] Feedback-driven plan adjustment")
    profile4 = SCENARIOS[3]["user_profile"]
    try:
        update_user_profile(profile4["user_id"], profile4)
        print("  ✓ Profile seeded")
        fb = log_feedback(profile4["user_id"], "lentil_soup", 1,
                          notes="too bland", symptoms_reported="bloating")
        print(f"  ✓ Feedback logged: avg_rating={fb['new_avg_rating']}, total={fb['total_meals_rated']}")

        plan = generate_meal_plan(
            profile4["user_id"],
            plan_type="daily",
            days=3,
            special_instructions="avoid legumes including lentils, beans, chickpeas due to sensitivity",
        )
        if "days" in plan:
            all_foods = [
                f["name"].lower()
                for day in plan["days"]
                for meal in day["meals"]
                for f in meal["foods"]
            ]
            legume_found = any(
                word in food
                for food in all_foods
                for word in ["lentil", "dal", "bean", "chickpea", "chana"]
            )
            if legume_found:
                print(f"  ✗ FAIL: Legumes found in adjusted plan despite feedback: {all_foods}")
            else:
                print(f"  ✓ Adjusted plan contains no legumes ({len(all_foods)} foods listed)")
        else:
            print(f"  Plan result: {list(plan.keys())}")
    except Exception as e:
        print(f"  ✗ EXCEPTION: {e}")

    # ---- Test: get_nutrition_data ----
    print("\n[TOOL TEST] get_nutrition_data")
    try:
        nd = get_nutrition_data("brown rice", 200)
        if "error" in nd:
            print(f"  ✗ FAIL: {nd}")
        else:
            p100 = nd["per_100g"]
            print(f"  ✓ Brown rice (200g): {nd['for_quantity']['calories_kcal']} kcal, "
                  f"{nd['for_quantity']['protein_g']}g protein, "
                  f"{nd['for_quantity']['carbs_g']}g carbs")
    except Exception as e:
        print(f"  ✗ EXCEPTION: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NutriMind Test Conversations")
    parser.add_argument("--live", action="store_true", help="Run live tests against real API")
    args = parser.parse_args()

    if args.live:
        # Verify required env vars
        required = ["WATSONX_APIKEY", "WATSONX_URL", "WATSONX_PROJECT_ID",
                    "CLOUDANT_URL", "CLOUDANT_APIKEY"]
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            print(f"ERROR: Missing required environment variables: {missing}")
            sys.exit(1)
        run_live(SCENARIOS)
    else:
        ok = run_dry(SCENARIOS)
        sys.exit(0 if ok else 1)
