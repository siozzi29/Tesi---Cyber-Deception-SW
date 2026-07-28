import csv
import random
import uuid

def generate_wordpress_traffic(num_requests=500):
    traffic = []
    
    # Costanti
    ver_list = ["1.0", "7.0.1", "6.5", "5.4.2", "efaa5193bbad9c60ffd1", "96a846e1d7b789c39ab9"]
    actions = ["heartbeat", "fetch-list", "update-meta", "autosave"]
    
    # Helper functions
    def get_id(): return random.randint(1, 100)
    def get_ver(): return random.choice(ver_list)
    
    for _ in range(num_requests):
        choice = random.choices(
            population=["public", "rest", "rss", "static", "admin_get", "admin_post"],
            weights=[30, 15, 10, 20, 15, 10],
            k=1
        )[0]
        
        if choice == "public":
            url = random.choice([
                "/",
                f"/?page_id={get_id()}",
                f"/?p={get_id()}",
                f"/?cat={get_id()}",
                f"/?author={get_id()}",
                f"/?s=search+query+{get_id()}",
                f"/?m=202607",
                f"/?p={get_id()}&replytocom={get_id()}"
            ])
            traffic.append([url, "GET", "", "text/html; charset=UTF-8", 0])
            
        elif choice == "rest":
            url = random.choice([
                "/index.php?rest_route=/",
                f"/index.php?rest_route=/wp/v2/posts/{get_id()}",
                f"/index.php?rest_route=/wp/v2/pages/{get_id()}",
                f"/index.php?rest_route=/wp/v2/users/{get_id()}",
                f"/index.php?rest_route=/wp/v2/categories/{get_id()}",
                "/index.php?rest_route=/wp/v2/comments"
            ])
            traffic.append([url, "GET", "", "application/json; charset=UTF-8", 0])
            
        elif choice == "rss":
            url = random.choice([
                "/?feed=rss2",
                "/?feed=comments-rss2",
                f"/?feed=rss2&p={get_id()}",
                f"/?feed=rss2&cat={get_id()}",
                f"/?feed=rss2&author={get_id()}"
            ])
            traffic.append([url, "GET", "", "application/rss+xml; charset=UTF-8", 0])
            
        elif choice == "static":
            ext = random.choice(["css", "js", "jpg", "png", "woff2"])
            if ext == "css":
                url = f"/wp-content/themes/twentytwentyfive/style.css?ver={get_ver()}"
                ct = "text/css"
            elif ext == "js":
                url = f"/wp-includes/js/comment-reply.min.js?ver={get_ver()}"
                ct = "application/javascript"
            else:
                url = f"/wp-content/uploads/2026/07/image_{get_id()}.{ext}"
                ct = f"image/{ext}" if ext != "woff2" else "font/woff2"
            traffic.append([url, "GET", "", ct, 0])
            
        elif choice == "admin_get":
            url = random.choice([
                "/wp-admin/",
                "/wp-admin/edit.php",
                f"/wp-admin/post.php?post={get_id()}&action=edit",
                "/wp-admin/post-new.php",
                "/wp-admin/plugins.php",
                "/wp-admin/options-general.php",
                f"/wp-admin/admin-ajax.php?action={random.choice(actions)}"
            ])
            traffic.append([url, "GET", "", "text/html; charset=UTF-8", 0])
            
        elif choice == "admin_post":
            sub_choice = random.choice(["login", "post", "comment", "ajax"])
            if sub_choice == "login":
                url = "/wp-login.php"
                content = "log=admin&pwd=secretpassword&wp-submit=Log+In&redirect_to=%2Fwp-admin%2F"
                ct = "application/x-www-form-urlencoded"
            elif sub_choice == "post":
                url = "/wp-admin/post.php"
                content = f"post_ID={get_id()}&action=editpost&post_title=New+Title&post_content=Content+goes+here"
                ct = "application/x-www-form-urlencoded"
            elif sub_choice == "comment":
                url = "/wp-comments-post.php"
                content = f"author=User&email=test%40test.com&comment=This+is+a+comment&comment_post_ID={get_id()}"
                ct = "application/x-www-form-urlencoded"
            else:
                url = "/wp-admin/admin-ajax.php"
                content = f"action={random.choice(actions)}&_ajax_nonce={uuid.uuid4().hex[:10]}"
                ct = "application/x-www-form-urlencoded"
            
            traffic.append([url, "POST", content, ct, 0])

    return traffic

if __name__ == "__main__":
    new_traffic = generate_wordpress_traffic(500)
    
    # Append to existing file
    file_path = "c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/data/wordpress_normal.csv"
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in new_traffic:
            writer.writerow(row)
            
    print(f"Generated and appended {len(new_traffic)} new WordPress requests to {file_path}")
