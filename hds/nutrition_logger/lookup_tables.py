"""
nutrition_logger/lookup_tables.py
===================================
Curated CoFID food code lookup table.
Built from 3 years of dietary diary analysis.
"""

COFID_LOOKUP = {
    # Dairy
    "whole milk":              "12-596",  # Milk, whole, pasteurised, average
    "semi skimmed milk":       "12-313",  # Milk, semi-skimmed, pasteurised, average
    "skimmed milk":            "12-310",  # Milk, skimmed, pasteurised, average
    "full fat milk":           "12-596",
    "butter":                  "17-685",  # Butter, salted
    "unsalted butter":         "17-661",
    "cheddar":                 "12-346",  # Cheese, Cheddar, English
    "cheddar cheese":          "12-346",
    "greek yoghurt":           "12-555",  # Yogurt, Greek style, plain
    "greek yogurt":            "12-555",
    "plain yoghurt":           "12-371",  # Yogurt, plain, whole milk
    "cream cheese":            "12-349",
    "double cream":            "12-330",
    "single cream":            "12-328",
    # Eggs
    "eggs scrambled":          "12-963",  # Eggs, chicken, whole, scrambled, without milk
    "scrambled eggs":          "12-963",
    "boiled egg":              "12-940",  # Eggs, chicken, whole, boiled
    "fried egg":               "12-947",  # Eggs, chicken, whole, fried
    "poached egg":             "12-950",  # Eggs, chicken, whole, poached
    "raw egg":                 "12-931",  # Eggs, chicken, whole, raw, value
    # Grains
    "oats":                    "11-788",  # Porridge oats, unfortified
    "rolled oats":             "11-788",
    "porridge oats":           "11-788",
    "white bread":             "11-980",  # Bread, white, sliced
    "wholemeal bread":         "11-981",  # Bread, wholemeal, average
    "brown bread":             "11-983",  # Bread, brown, average
    "rye bread":               "11-984",  # Bread, rye, average
    "white rice cooked":       "11-862",  # Rice, white, long grain, boiled
    "rice white cooked":       "11-862",
    "basmati rice cooked":     "11-858",  # Rice, white, basmati, boiled
    "brown rice cooked":       "11-869",  # Rice, brown, wholegrain, boiled
    "rice brown cooked":       "11-869",
    "pasta cooked":            "11-1129", # Pasta, white, dried, boiled
    "pasta white cooked":      "11-1129",
    "pasta wholemeal cooked":  "11-723",  # Pasta, wholewheat, boiled
    "couscous cooked":         "11-804",  # Couscous, cooked
    "quinoa cooked":           "11-819",  # Quinoa, cooked
    # Meat
    "chicken breast grilled":  "18-323",  # Chicken, breast, grilled without skin, meat only
    "chicken breast raw":      "18-100",  # Chicken, breast, raw, meat only
    "chicken breast baked":    "18-323",
    "chicken thigh grilled":   "18-331",  # Chicken, thigh, grilled, meat only
    "beef mince cooked":       "18-470",  # Beef, mince, stewed
    "beef mince raw":          "18-469",
    "beef mince":              "18-470",
    "salmon raw":              "16-356",  # Salmon, farmed, flesh only, raw
    "salmon fillet raw":       "16-356",
    "salmon baked":            "16-359",  # Salmon, farmed, flesh only, baked
    "salmon grilled":          "16-359",
    "salmon fillet":           "16-359",
    "tuna canned brine":       "16-416",  # Tuna, canned in brine, drained
    "tuna canned":             "16-416",
    "tuna canned oil":         "16-417",  # Tuna, canned in sunflower oil, drained
    "sardines canned oil":     "16-440",  # Sardines, canned in olive oil, drained
    "sardines canned":         "16-424",  # Sardines, canned in brine, drained
    "cod baked":               "16-175",  # Cod, baked
    "cod raw":                 "16-168",
    "mackerel grilled":        "16-241",  # Mackerel, grilled
    # Vegetables
    "broccoli raw":            "13-502",  # Broccoli, green, raw
    "broccoli cooked":         "13-503",  # Broccoli, green, boiled
    "spinach raw":             "13-521",  # Spinach, baby, raw
    "spinach cooked":          "13-524",  # Spinach, boiled
    "sweet potato raw":        "13-463",  # Sweet potato, raw, flesh only
    "sweet potato baked":      "13-464",  # Sweet potato, baked
    "sweet potato cooked":     "13-465",  # Sweet potato, boiled
    "cherry tomatoes":         "13-477",  # Tomatoes, cherry, raw
    "tomatoes raw":            "13-474",  # Tomatoes, raw
    "avocado":                 "14-386",  # Avocado, Hass, flesh only
    "cucumber":                "13-488",
    "carrots raw":             "13-484",
    "carrots cooked":          "13-485",
    "onion raw":               "13-493",
    "garlic":                  "13-491",
    "mushrooms raw":           "13-492",
    "mushrooms cooked":        "13-490",
    "kale raw":                "13-505",
    "peppers raw":             "13-496",
    "courgette raw":           "13-487",
    # Fruit
    "banana":                  "14-318",  # Bananas, flesh only
    "apple":                   "14-319",  # Apples, eating, raw, flesh and skin
    "blueberries":             "14-325",
    "strawberries":            "14-330",
    "raspberries":             "14-328",
    "orange":                  "14-370",
    "mango":                   "14-351",
    "grapes":                  "14-340",
    # Legumes
    "chickpeas cooked":        "13-662",  # Beans, chick peas, boiled
    "chickpeas":               "13-662",
    "lentils cooked":          "13-658",  # Lentils, red, split, boiled
    "red lentils cooked":      "13-658",
    "kidney beans cooked":     "13-657",
        "edamame":                 "13-649",
    # Nuts & seeds
    "almonds":                 "14-870",  # Almonds, flaked and ground
    "walnuts":                 "14-879",  # Walnuts, kernel only
    "cashews":                 "14-874",
    "peanuts":                 "14-876",
    "pumpkin seeds":           "14-884",
    "sunflower seeds":         "14-886",
    "chia seeds":              "14-893",
    "flaxseed":                "14-882",
    # Fats & oils
    "olive oil":               "17-038",
    "coconut oil":             "17-031",
    "rapeseed oil":            "17-040",
    "sunflower oil":           "17-043",
    # Other

    # ── Personalised lookup (built from 3 years of dietary diary) ──────────────
    # Oils
    "extra virgin olive oil":       "17-038",
    "olive oil":                    "17-038",
    # Grains & noodles
    "rice white long grain cooked": "11-862",
        "quinoa cooked":                "11-819",
    "buckwheat cooked":             "11-820",
    "millet cooked":                "11-821",
    "buckwheat dry":                "11-022",
    "sourdough bread":              "11-981",  # use wholemeal as proxy
    # Vegetables
    "aubergine cooked":             "13-651",  # Aubergine, flesh and skin, boiled
    "aubergine boiled":             "13-651",
    "eggplant cooked":              "13-651",
    "green beans cooked":           "13-654",  # Beans, runner, boiled
    "green bean boiled":            "13-654",
    "spinach cooked":               "13-550",  # Spinach, baby, boiled
    "courgette cooked":             "13-628",  # Courgette, boiled
    "zucchini cooked":              "13-628",
    "tomato cooked":                "13-479",  # Tomatoes, stewed
    "tomato boiled":                "13-479",  # Tomatoes, stewed
    "tomato raw":                   "13-517",  # Tomatoes, standard, raw
    "cherry tomatoes":              "13-519",
    "okra cooked":                  "13-652",
    "pumpkin cooked":               "13-549",
    "cauliflower cooked":           "13-513",
    "cabbage green cooked":         "13-511",
    "cabbage red cooked":           "13-540",
    "kale cooked":                  "13-649",
    "bok choy cooked":              "13-516",  # Pak choi, steamed
    "pak choi cooked":              "13-516",
    "butternut squash":             "13-644",
    "butternut squash baked":       "13-644",
    "celeriac cooked":              "13-585",
    "cucumber raw":                 "13-523",
    "avocado":                      "14-386",
    "peach raw":                    "14-299",
    "shiitake cooked":              "13-295",
    "maitake raw":                  "13-294",  # closest mushroom
    # Eggs
    "egg raw":                      "12-937",  # Eggs, chicken, whole, raw
    "egg whole raw":                "12-937",
    "duck egg":                     "12-920",  # Eggs, duck, whole, raw
    "duck eggs":                    "12-920",
    "egg white cooked":             "12-941",  # Eggs, chicken, white, boiled
    "egg scrambled":                "12-963",
    # Dairy
    "whole milk":                   "12-596",
    "a2 whole milk":                "12-596",
    "goat cheese soft":             "12-357",
    "goat cheese":                  "12-357",
    # Nuts & seeds
    "walnuts":                      "14-879",
    "almonds raw":                  "14-896",  # Almonds, whole kernels
    "almonds":                      "14-896",
    "macadamia nuts raw":           "14-891",
    "macadamia nuts":               "14-891",
    "cashews raw":                  "14-811",
    "cashews":                      "14-811",
    # Legumes
    "lentils boiled":               "13-658",  # Lentils, red, split, boiled
    "lentils cooked":               "13-658",
    "white beans boiled":           "13-087",
        "kidney beans":                 "13-659",  # Beans, red kidney, boiled
    "adzuki beans":                 "13-655",  # Beans, adzuki, boiled
    # Protein & meat
    "chicken breast skinless cooked": "18-323",  # Chicken, breast, grilled without skin
    "chicken breast cooked":          "18-323",
    "chicken thigh skin removed":     "18-331",  # Chicken thigh, grilled meat only
    # Starches
    "potato boiled":                "13-605",  # Potatoes, old, boiled, flesh only
    "potato baked":                 "13-620",  # Potatoes, old, baked, flesh only
    "potatoes baked flesh and skin": "13-491",  # Potatoes, old, baked, flesh and skin
    "sweet potato baked":           "13-672",
    "sweet potato boiled":          "13-646",  # Sweet potato, flesh only, boiled
    # Bread
    "white bread":                  "11-980",
    # Other
    "honey":                        "17-050",
    # ── Exact search terms from validation (Claude-generated) ──────────────────
    # These keys match EXACTLY what Claude generates as search terms
    "mushrooms cooked":             "13-505",  # Mushrooms, white, raw (closest in CoFID)
    "carrots cooked":               "13-497",  # Carrots, old, boiled
    "asparagus cooked":             "13-638",  # Asparagus, steamed
    "oil olive":                    "17-038",   # Claude generates this for olive oil
    "oil extra virgin olive":       "17-038",
    "egg raw whole":                "12-937",   # Whole egg raw
    "egg chicken raw":              "12-937",
    "broccoli green boiled":        "13-503",   # Regular broccoli boiled
    "broccoli fresh cooked":        "13-503",
    "broccoli cooked fresh":        "13-503",
    "courgette boiled":             "13-628",
    "courgette fresh cooked":       "13-628",
    "aubergine boiled":             "13-651",
    "aubergine fresh cooked":       "13-651",
    "chicken breast skinless":      "18-323",
    "chicken breast skinless cooked":"18-323",
    "beans black boiled":           "13-063",  # Beans, blackeye - closest to black beans in CoFID
    "black beans boiled":           "13-063",
    "black beans canned":           "13-063",
    "beans black canned":           "13-063",
    "mushrooms common boiled":      "13-505",  # Mushrooms, white, raw
    "mushroom fresh cooked":        "13-505",
    "mushrooms fresh cooked":       "13-505",
    "cauliflower boiled":           "13-513",
    "cauliflower fresh cooked":     "13-513",
        "rice white long grain":        "11-862",
    "rice white enriched cooked":   "11-862",
    "salad tossed":                 "15-648",
    "salad mixed greens":           "15-648",
    "salad mixed greens dressing":  "15-648",
    "red wine":                     "17-752",
    "cod liver oil":                "17-488",
    "hazelnut butter":              "14-874",
    "cashew butter":                "14-811",
    "hummus":                       "13-556",
    "houmous":                      "13-556",
    "fennel raw":                   "13-241",
    "fennel bulb raw":              "13-241",
    "swiss chard cooked":           "13-224",
    "chard cooked":                 "13-224",
    "artichoke cooked":             "13-154",
    "globe artichoke":              "13-154",
    "red pepper raw":               "13-524",
    "red bell pepper raw":          "13-524",
    "garlic raw":                   "13-491",
    "courgette raw":                "13-627",
    "zucchini raw":                 "13-627",
    "tossed salad":                 "15-648",
    "green salad":                  "15-648",
    "asparagus cooked":             "13-591",
    
    "mushrooms cooked":             "13-297",
    "mushroom boiled":              "13-297",
    "cauliflower cooked":           "13-513",
    "cauliflower boiled":           "13-513",
    "pesto":                        "15-838",
    "lentil soup":                  "17-808",
    "tossed salad with dressing":   "15-648",
    "honey":                   "17-118",
    "sugar":                   "17-079",
    "soy sauce":               "17-150",
    "tomato puree":            "13-480",
}
