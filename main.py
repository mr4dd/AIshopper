#!/usr/bin/env python3

import requests
from flask import Flask
from flask import render_template
from flask import request
from dotenv import load_dotenv
from bs4 import BeautifulSoup

import os
import google.generativeai as genai

import time

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


app = Flask(__name__)


def retrieveListings(ProductName, City, MaxPrice):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0"
    }
    response = requests.get(
        f"https://www.avito.ma/fr/{City}/{ProductName}--%C3%A0_vendre?has_price=true&has_image=true&price={MaxPrice}",
        headers=headers,
    )
    html = response.text
    return html


def preProcess(html, MaxPrice):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0"
    }
    listingClass = "sc-1jge648-0 eTbzNs"  # tag type = a
    priceClass = "sc-1x0vz2r-0 eCXWei sc-b57yxx-3 IneBF"
    uploadDateClass = "sc-1x0vz2r-0 iFQpLP"
    DescriptionClass = "sc-ij98yj-0 fAYGMO"
    soup = BeautifulSoup(html, "html.parser")
    listings = soup.find_all(class_=listingClass)

    listingsDicts = []

    for i, listing in enumerate(listings):
        title = listing.find(class_="sc-1x0vz2r-0 czqClV").text
        url = listing.get("href")
        uploadDate = listing.find(class_=uploadDateClass).text
        price = listing.find(class_=priceClass).text

        if int(price.strip(" DH").replace(",", "")) <= MaxPrice:

            response = requests.get(url, headers=headers).text
            soup = BeautifulSoup(response, "html.parser")
            description = soup.find(class_=DescriptionClass).text

            listingBuild = {
                "title": title,
                "price": price,
                "uploadDate": uploadDate,
                "url": url,
                "description": description,
            }
            listingsDicts.append(listingBuild)
    return listingsDicts

def getNext(rawHTML, visitedURLs):
    nextPageClass = "sc-1cf7u6r-0 gRyZxr sc-2y0ggl-1 yRCEb"
    soup = BeautifulSoup(rawHTML, "html.parser")
    nextPage = soup.find_all(class_=nextPageClass)[-1]
    if len(nextPage) == 0:
        return "STOP_SCRAPING"
    url = nextPage.get("href")
    if url in visitedURLs:
        return "STOP_SCRAPING"
    return url

def retrieveAll(rawHTML, MaxPrice):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0"
    }
    listings = [preProcess(rawHTML, MaxPrice)]
    visitedURLs = []
    while True:
        nextURL = getNext(rawHTML, visitedURLs)
        if nextURL == "STOP_SCRAPING":
            return listings
        visitedURLs.append(nextURL)
        rawHTML = requests.get(nextURL, headers=headers).text
        listing = preProcess(rawHTML, MaxPrice)
        listings.append(listing)
        time.sleep(0.3)

    return listings

def fetchImageLinks(listings):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0"
    }
    imageClass = "sc-1gjavk-0 fpXQoT"
    images = []
    newListings = []
    
    # Iterate through the listings, skipping in increments of 3 as per the original intent
    for i in range(0, len(listings), 3):
        try:
            if i+2 <= len(listings):
                url = listings[i+2]
            else:
                images.append("none")
                url = " "
            if "http" in url:
                response = requests.get(url, headers=headers).text
                soup = BeautifulSoup(response, "html.parser")
                imageTag = soup.find(class_=imageClass)
                if imageTag and imageTag.get("src"):
                    imageURL = imageTag.get("src")
                    images.append(imageURL)
        except (IndexError, requests.RequestException) as e:
            # Handle any index or request errors gracefully
            print(f"Error fetching image from URL: {url} - {e}")
            continue
    # Merge listings with images
    for i in range(0, len(listings), 3):
        try:
            newListings.append(images[i//3])    # Add the corresponding image URL
            newListings.append(listings[i])       # Listing element 1
            newListings.append(listings[i+1])     # Listing element 2
            newListings.append(listings[i+2])     # Listing element 3
        except IndexError:
            print("Error merging listings and images.")
            continue
    
    return newListings

def analyzeListings(listings, Description, MaxPrice):
    # send off to gemini for analysis
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = 'You are pawnBot, an AI model designed to read the descriptions and posting dates of online listings and determine if they are worth taking a look at by a human user, how you determine that is by comparing the listing description to the user-provided description, and making sure that the listing is no older than 3 months. the listings are in the format of listingBuild = [{"title": title,"price": price,"uploadDate": uploadDate,"url": url,"description": description}, {"title": title,"price": price,"uploadDate": uploadDate,"url": url,"description": description}, ...], you will respond with the name, price and url of each one that fits the bill, and if none fit exactly you will respond with the closest 3 matches without any chat or banter, just the listings without markdown or html formatting, separating each individual listing by a new line in this format: title \n price \n url and remember, this output needs to be consistent, no variations allowed. now here are the listings: '
    response = model.generate_content(
        prompt
        + str(listings)
        + "and this is the description provided by user: "
        + Description
    )
    return response.text.split("\n")


@app.route("/")
def main():
    return render_template("index.html")


@app.route("/shop", methods=["POST"])
def shopMain():
    error = None
    ProductName = request.form["pn"]
    City = request.form["c"]
    MaxPrice = int(request.form["mp"])
    Description = request.form["desc"]
    if not ProductName or not City or not MaxPrice or not Description:
        error = "Please fill all the fields out"
        return render_template("error.html", error=error)
    rawHTML = retrieveListings(ProductName, City, MaxPrice)
    allListings = retrieveAll(rawHTML, MaxPrice)
    goodListings = analyzeListings(allListings, Description, MaxPrice)
    goodListings.pop()
    goodListingsWithImages = fetchImageLinks(goodListings)
    return render_template("listings.html", listings=goodListingsWithImages)
