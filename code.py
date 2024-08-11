# %% [markdown]
# # Import selenium and required webdriver
# - **Challange**: We have diffrent browsers in a team and we want a working solution for all common browsers.
# - **Solution1**: Use selenium-manager. But i don't like this solution because selenium-manager is not installed by default.
# - **Solution2 (Selected)**: We should write a code to find and import a browser along with it's webdriver.

# %%
# General imports
from typing import Any, Dict, List
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
import re
import os
import asyncio
import json
import importlib
import time

# Simple imports incase of emergency
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.chrome.webdriver import WebDriver as WebDriver
# options = Options()
# options.page_load_strategy = "eager"
# # launch the browser
# driver = WebDriver(
#     options=options, service=Service(executable_path="/usr/bin/chromedriver")
# )

# user priorities on webdrivers and then browsers
driver_priority = [
    "geckodriver",
    "chromedriver",
]
browser_priority = {
    "geckodriver": ["firefox"],
    "chromedriver": ["chromium", "chrome"],
}

# constants
BROWSER_SELENIUM_CLASSES = {
    "firefox": ("Options", "Service", "WebDriver"),
    "chrome": ("Options", "Service", "WebDriver"),
    "chromium": ("ChromiumOptions", "ChromiumService", "ChromiumDriver"),
}

# os paths to find binaries
base_bin_path = [""]
base_bin_path.extend(os.environ["PATH"].split(os.pathsep))
bin_postfix = ""
if os.name == "nt":  # windows
    bin_postfix = ".exe"

def find_executable_path(filename):
    for p in base_bin_path:
        file_path = os.path.join(p, filename + bin_postfix)
        if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
            return file_path
    return None

# Now it's time to find and import a working webdriver+browser
options = None
driver = None
found = False
for d in driver_priority:
    driver_path = find_executable_path(d)
    if driver_path:
        for b in browser_priority[d]:
            browser_path = find_executable_path(b)
            if browser_path:
                # try to import like:
                # from selenium.webdriver.{b}.options import Options, Service, WebDriver
                options_module = importlib.import_module(f"selenium.webdriver.{b}.options")
                Options = getattr(options_module, BROWSER_SELENIUM_CLASSES[b][0])

                service_module = importlib.import_module(f"selenium.webdriver.{b}.service")
                Service = getattr(service_module, BROWSER_SELENIUM_CLASSES[b][1])

                webdriver_module = importlib.import_module(f"selenium.webdriver.{b}.webdriver")
                WebDriver = getattr(webdriver_module, BROWSER_SELENIUM_CLASSES[b][2])

                options = Options()
                options.page_load_strategy = "eager"

                found = True
                print(browser_path, driver_path)
                break
    if found:
        break
if not found:
    print("No working webdriver+browser found!")
    exit()

# %%
# 
def new_driver():
    return WebDriver(
    options=options, service=Service(executable_path=driver_path)
    )

# %% [markdown]
# # Find elements utitlites

# %%
DEFAULT_LONG_TIMEOUT = 99999
DEFAULT_SHORT_TIMEOUT = 1

async def run_async(*args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, *args)

async def find_if_page_loaded(root_element, selector, driver):
    # Wait until the page is fully loaded
    await run_async(
            WebDriverWait(driver, timeout=DEFAULT_LONG_TIMEOUT).until,
            lambda driver: driver.execute_script("return document.readyState") in ["interactive","complete"]
            )

    # Try to find the element
    try:
        if root_element is None:
            return await run_async(
                WebDriverWait(driver, timeout=DEFAULT_SHORT_TIMEOUT).until,
                EC.presence_of_all_elements_located(selector)
            )
        else:
            return await run_async(root_element.find_elements, selector[0], selector[1])
    except Exception as e:
        # print(e)
        return None 

async def click_on(selector, driver):
    # Wait until the page is fully loaded
    await run_async(
            WebDriverWait(driver, timeout=DEFAULT_LONG_TIMEOUT).until,
            lambda driver: driver.execute_script("return document.readyState") in ["interactive","complete"]
            )
    try:
        e = await run_async(
            WebDriverWait(driver, timeout=DEFAULT_SHORT_TIMEOUT).until,
            EC.element_to_be_clickable(selector)
        )
        # click using js (nothing will stop js from clicking that element even obscuring by another element ...)
        driver.execute_script("arguments[0].click()", e)
    except Exception as e:
        # print(e)
        pass

async def fetch_data(root_element, data_selector_map: Dict[str, Dict[str, Any] | List[Dict[str, Any]]], driver):
    data = {}
    for k, v in data_selector_map.items():
        if isinstance(v, List):
            selector_object = v[0]
        else:
            selector_object = v

        # "before_commands" phase
        if "before_commands" in selector_object:
            for f in selector_object["before_commands"]:
                await f

        # "selector" phase
        elements = []
        if "selector" in selector_object:
            if isinstance(root_element, List):
                for e in root_element:
                    e = await find_if_page_loaded(e ,selector_object["selector"], driver)
                    if e is not None:
                        elements.extend(e)
            else:
                elements = await find_if_page_loaded(root_element ,selector_object["selector"], driver)
        else: # if "selector" does not specified in selector_object then use root_element as the main element in the current flow
            elements = root_element
        if elements is None or len(elements) == 0:
            data[k] = None
            continue

        if not isinstance(v, List):
            elements = elements[0]

        # "find_elements" phase
        if "find_elements" in selector_object:
            elements = await fetch_data(elements, selector_object["find_elements"], driver)
        # default behavior when none of "after_commands" and "find_elements" exist 
        elif "after_commands" not in selector_object:
            if isinstance(elements, List):
                elements = [e.text for e in elements]
            else:
                elements = elements.text

        # "after_commands" phase
        if "after_commands" in selector_object:
            try:
                if isinstance(elements, List):
                    for f in selector_object["after_commands"]:
                        elements = [f(e) for e in elements]
                else:
                    for f in selector_object["after_commands"]:
                        elements = f(elements)
            except Exception as e:
                elements = None

        data[k] = elements
    return data

# %% [markdown]
# # search and list articles urls
# - Challenge 1: order of findings is not the same all of the time because of asyncio concurrency
# - Solution 1: each producer should be aware of the rank of article url ...

# TODO: filter course urls
# TODO: headless browser

# %%
async def async_get_url(driver, url):
    # loop = asyncio.get_running_loop()
    # await loop.run_in_executor(None, driver.get, url)
    await run_async(driver.get, url)

async def producer(queryparams, queue, driver):
    url = f"https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={queryparams['search']}&pageNumber={queryparams['page_num']}"
    url += queryparams["extra"]
    try:
        while True:
            try:
                await async_get_url(driver, url)
            except Exception as e:
                print("Producer Failed at async_get_url, getting up again 💪 ... ")
                continue

            # find list of articles
            lis = []
            while len(lis)==0 : # ensure there are any results (gaurd against wrong results from selenium)
                lis = await find_if_page_loaded(None, (By.CLASS_NAME, "List-results-items"), driver)
                lis = lis if lis is not None else []

            for i, li in enumerate(lis):
                article = await find_if_page_loaded(
                    li,
                    (
                        By.CSS_SELECTOR,
                        "div:nth-child(1) > div:nth-child(1) > div:nth-child(2) > h3:nth-child(1) > a:nth-child(1)",
                    ),
                    driver,
                )
                if article is not None and len(article) > 0:
                    article = article[0]
                    print(article.text)
                    # put url of article on the queue
                    url = article.get_attribute("href")

                    # ommit course urls
                    if not url.startswith("https://ieeexplore.ieee.org/courses/"):
                        await queue.put(((queryparams["page_num"], i), article.get_attribute("href")))
            break
    finally: 
        driver.close()


async def consumer(in_queue, out_queue, driver):
    try:
        while True:
            input_data = await in_queue.get()
            rank = input_data[0] 
            article_url = input_data[1]

            try:
                await async_get_url(driver, article_url)
            except Exception as e:
                print("Worker Failed at async_get_url, getting up again 💪 ... ")
                in_queue.task_done()
                await in_queue.put(input_data)
                continue


            data_selector_map = {
                "Title" : {"selector":(By.CSS_SELECTOR, ".document-title > span:nth-child(1)")},
                "Page(s)" : {
                    "selector": (By.CSS_SELECTOR, "div.col-6:nth-child(1) > div:nth-child(1)"),
                    "after_commands": [
                        lambda x: re.findall(r"Page\(s\): (.*)", x.text)[0],
                        lambda x: x.split(),
                        lambda x: int(x[2]) - int(x[0]) + 1,
                    ]
                },
                "Cites in Papers" :{
                    "selector": (By.CSS_SELECTOR, "button.document-banner-metric:nth-child(1) > div:nth-child(1)"),
                    "after_commands": [lambda x: int(x.text)],
                },
                "Cites in Patent" : {
                    "selector": (By.CSS_SELECTOR, "button.document-banner-metric:nth-child(2) > div:nth-child(1)"),
                    "after_commands": [lambda x: int(x.text)],
                },
                "Full Text Views" : {
                    "selector": (By.CSS_SELECTOR, "button.document-banner-metric:nth-child(3) > div:nth-child(1)"),
                    "after_commands": [lambda x: int(x.text)],
                },
                "Publisher" : {"selector": (By.CSS_SELECTOR, ".publisher-title-tooltip > xpl-publisher:nth-child(1) > span:nth-child(1) > span:nth-child(1) > span:nth-child(1) > span:nth-child(2)")},
                "DOI" : {"selector": (By.CSS_SELECTOR, ".stats-document-abstract-doi > a:nth-child(2)")},
                "Date of Publication" : {
                    "selector": (By.CSS_SELECTOR, ".doc-abstract-pubdate"),
                    "after_commands": [
                        lambda x: re.findall(r"Date of Publication: (.*)", x.text)[0],
                    ]
                },
                "Abstract" : {"selector":(By.CSS_SELECTOR, "div.u-mb-1:nth-child(1) > div:nth-child(2)")},
                "Published in" : [
                    {
                        "selector": (By.CSS_SELECTOR, "a.stats-document-abstract-publishedIn, .stats-document-abstract-publishedIn > a:nth-child(2)"), 
                        "find_elements": {
                            "name" : {},
                            "link" : {"after_commands": [lambda x: x.get_attribute("href")]}
                        }
                    }
                ],
                "Authors": [
                    {
                        "before_commands": [click_on((By.CSS_SELECTOR, '#authors-header'), driver)],
                        "selector": (By.XPATH, '//*[@id="authors"]//*[@class="authors-accordion-container"]'),
                        "find_elements":{
                            # css selctor should be more dynamic and not too exact to avoid null values: (div istead of div:nth-child(1))
                            "name": [{"selector":(By.CSS_SELECTOR, "xpl-author-item:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div > div:nth-child(1)")}],
                            "from": [{"selector":(By.CSS_SELECTOR, "xpl-author-item:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div > div:nth-child(2)")}]
                        },
                        "after_commands":[lambda x: [{'name': n, 'from': f} for n, f in zip(x['name'], x['from'])]]
                    }
                ],
                "IEEE Keywords": [
                    {
                        "before_commands": [click_on((By.CSS_SELECTOR, '#keywords-header'), driver)],
                        "selector": (By.XPATH, '//*[@id="keywords"]//li[.//strong[text()="IEEE Keywords"]]//ul'),
                        "find_elements":{
                            "tags": [{"selector":(By.TAG_NAME, "li"), "after_commands": [lambda x: x.text.strip(",\n")]}],
                        },
                        "after_commands":[lambda x: x["tags"] ,lambda x: [item for sublist in x for item in sublist.split(", ")]]
                    }
                ],
                "Author Keywords": [
                    {
                        "selector": (By.XPATH, '//*[@id="keywords"]//li[.//strong[text()="Author Keywords"]]//ul'),
                        "find_elements":{
                            "tags": [{"selector":(By.TAG_NAME, "li"), "after_commands": [lambda x: x.text.strip(",\n")]}],
                        },
                        "after_commands":[lambda x: x["tags"] ,lambda x: [item for sublist in x for item in sublist.split(", ")]]
                    }
                ]
            }

            # find needed data
            try:
                data = await fetch_data(None ,data_selector_map, driver)
            except Exception as e:
                print("Worker Failed at fetch_data, getting up again 💪 ... ")
                in_queue.task_done()
                await in_queue.put(input_data)
                continue

            # insert the last things into the data {}
            data["url"] = article_url
            data["rank"] = rank

            in_queue.task_done()
            out_queue.put_nowait(data)
    finally:
        driver.close()


# %%
search = "linux"
page = 5

# TODO: dynamically change this option
num_of_consumers = 5

async def main():
    producers = []
    consumers = []
    urls_queue = asyncio.Queue()
    data_queue = asyncio.Queue()

    for i in range(1, page + 1):
        # add "&sortType=newest" for newest if you need it ("&sortType=paper-citations", "&sortType=most-popular")
        queryparams = {"search": search, "page_num": i, "extra": "&sortType=newest"}
        producers.append(asyncio.create_task(producer(queryparams, urls_queue, new_driver())))

    # create consumer as needed
    for i in range(num_of_consumers):
        consumers.append(asyncio.create_task(consumer(urls_queue, data_queue, new_driver())))

    # create a task to print metrics
    metrics_task = asyncio.create_task(print_metrics(producers, consumers, urls_queue, data_queue))

    # with both producers and consumers running, wait for
    # the producers to finish
    await asyncio.gather(*producers)
    print('---- done producing')

    # wait for the remaining tasks to be processed
    await urls_queue.join()
    # cancel the consumers, which are now idle
    for c in consumers:
        c.cancel()    
    # cancel the metrics task
    metrics_task.cancel()

    # get processed data from consumers
    results = []
    while not data_queue.empty():
        results.append(await data_queue.get())
    
    results.sort(key= lambda x : x["rank"][1])
    results.sort(key= lambda x : x["rank"][0])

    with open('linux.json', 'w') as f:
        f.write(json.dumps(results, indent=2))

async def debug():
    q = asyncio.Queue()
    out_q = asyncio.Queue()
    # https://ieeexplore.ieee.org/document/8946141
    # https://ieeexplore.ieee.org/document/7467408
    # https://ieeexplore.ieee.org/document/8946223/
    q.put_nowait("https://ieeexplore.ieee.org/document/7467408")
    t = asyncio.create_task(consumer(q, out_q, new_driver()))
    await q.join()
    while not out_q.empty():
        data = await out_q.get()
        print(json.dumps(data, indent=2))
    t.cancel()

async def print_metrics(producers, consumers, urls_queue, data_queue):
    while True:
        # print metrics every 1 second
        await asyncio.sleep(1)
        print(f"URLs queue size: {urls_queue.qsize()}")


start_time = time.time()
asyncio.run(main())
end_time = time.time()
execution_time = end_time - start_time
print(f"Execution time: {execution_time:.2f} seconds")
