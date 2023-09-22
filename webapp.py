import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import openai
from playwright.sync_api import sync_playwright
from dataclasses import dataclass, asdict, field
import pandas as pd
from typing import List

# Part 1: Data Scraping and Google Sheets Integration

@dataclass
class Business:
    name: str = None
    address: str = None
    website: str = None
    email: str = None
    phone_number: str = None
    reviews_count: int = None
    reviews_average: float = None
    row_number: int = None

@dataclass
class BusinessList:
    business_list: List[Business] = field(default_factory=list)

    def dataframe(self):
        return pd.json_normalize(
            (asdict(business) for business in self.business_list), sep="_"
        )

    def save_to_csv(self, filename):
        self.dataframe().to_csv(f"{filename}.csv", index=False)

def scrape_google_maps(location, business_type, total):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto("https://www.google.com/maps", timeout=60000)
        page.wait_for_timeout(5000)

        search_for = f"{business_type} {location}"
        page.locator('//input[@id="searchboxinput"]').fill(search_for)
        page.wait_for_timeout(3000)

        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)

        page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')

        previously_counted = 0
        while True:
            page.mouse.wheel(0, 10000)
            page.wait_for_timeout(3000)

            if (
                    page.locator(
                        '//a[contains(@href, "https://www.google.com/maps/place")]'
                    ).count()
                    >= total
            ):
                listings = page.locator(
                    '//a[contains(@href, "https://www.google.com/maps/place")]'
                ).all()[:total]
                listings = [listing.locator("xpath=..") for listing in listings]
                print(f"Total Scraped: {len(listings)}")
                break
            else:
                if (
                        page.locator(
                            '//a[contains(@href, "https://www.google.com/maps/place")]'
                        ).count()
                        == previously_counted
                ):
                    listings = page.locator(
                        '//a[contains(@href, "https://www.google.com/maps/place")]'
                    ).all()
                    print(f"Arrived at all available\nTotal Scraped: {len(listings)}")
                    break
                else:
                    previously_counted = page.locator(
                        '//a[contains(@href, "https://www.google.com/maps/place")]'
                    ).count()
                    print(
                        f"Currently Scraped: ",
                        page.locator(
                            '//a[contains(@href, "https://www.google.com/maps/place")]'
                        ).count(),
                    )

        if len(listings) < total:
            print(f"Error: Found only {len(listings)} listings which is less than the required {total} listings.")
            browser.close()
            return None

        business_list = BusinessList()

        for listing in listings:
            listing.click()
            page.wait_for_timeout(5000)

            name_xpath = '//div[contains(@class, "fontHeadlineSmall")]'
            address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
            website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
            phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
            reviews_span_xpath = '//span[@role="img"]'

            business = Business()

            if listing.locator(name_xpath).count() > 0:
                business.name = listing.locator(name_xpath).inner_text()
            else:
                business.name = ""
            if page.locator(address_xpath).count() > 0:
                business.address = page.locator(address_xpath).inner_text()
            else:
                business.address = ""
            if page.locator(website_xpath).count() > 0:
                business.website = page.locator(website_xpath).inner_text()
                business.email = f"info@{business.website}"
            else:
                business.website = ""
                business.email = ""
            if page.locator(phone_number_xpath).count() > 0:
                business.phone_number = page.locator(phone_number_xpath).inner_text()
            else:
                business.phone_number = ""
            if listing.locator(reviews_span_xpath).count() > 0:
                reviews_text = listing.locator(reviews_span_xpath).get_attribute("aria-label").split()
                business.reviews_average = float(reviews_text[0].replace(",", "."))
                business.reviews_count = int(reviews_text[2].replace(",", ""))
            else:
                business.reviews_average = ""
                business.reviews_count = ""

            business_list.business_list.append(business)

        browser.close()
        return business_list

def authenticate_google_sheets():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('google_sheets_credentials.json', scope)
    gc = gspread.authorize(credentials)
    return gc

def append_to_google_sheets(gc, business_list, spreadsheet_key):
    worksheet = gc.open_by_key(spreadsheet_key).sheet1
    data_to_append = business_list.dataframe().values.tolist()
    worksheet.append_rows(data_to_append)

# Part 2: Personalized Email Generation using ChatGPT

openai.api_key = 'your_api_key'

def generate_personalized_email_content(lead, location, business_type):
    response = openai.Completion.create(
        engine="davinci",
        prompt = f"Dear {lead.name},\n\nI trust this message finds you well. My name is [Your Name], and I am reaching out to inquire about your esteemed {business_type} establishment located at {lead.address} in the beautiful {location}.",
        max_tokens=100
    )
    email_content = response.choices[0].text.strip()
    return email_content

def generate_personalized_emails_and_save(lead_list, location, business_type):
    for lead in lead_list:
        email_content = generate_personalized_email_content(lead, location, business_type)
        lead.email = email_content  # Save the generated email in the 'email' attribute of the Business object

# Part 3: Email Sending

def send_email(smtp_server, smtp_port, smtp_username, smtp_password, from_email, to_email, subject, email_content):
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(email_content, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        return True  # Email sent successfully
    except Exception as e:
        print(f"Failed to send email to {to_email}: {str(e)}")
        return False  # Email sending failed

# Create a Streamlit app
def app():
    st.title("Business Lead Scraper and Emailer")

    # Part 1: Data Scraping and Google Sheets Integration
    location = st.text_input("Enter the location:")
    business_type = st.text_input("Enter the type of business:")
    total = st.number_input("Enter the total number of listings to scrape:", min_value=1, step=1)
    spreadsheet_key = 'yor_key'  # Replace with your Google Sheets key
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    smtp_username = 'username'
    smtp_password = 'password'

    if st.button("Scrape and Send Emails"):
        # Part 1: Data Scraping and Google Sheets Integration
        business_list = scrape_google_maps(location, business_type, total)
        if business_list:
            gc = authenticate_google_sheets()
            worksheet = gc.open_by_key(spreadsheet_key).sheet1

            # Iterate through the business list and append a new row for each lead
            for lead in business_list.business_list:
                email_content = generate_personalized_email_content(lead, location, business_type)
                new_row = [lead.name, lead.address, lead.website, lead.email, lead.phone_number, lead.reviews_count,
                           lead.reviews_average, email_content]
                worksheet.append_row(new_row)

            # Part 2: Personalized Email Generation using ChatGPT
            for lead in business_list.business_list:
                email_content = generate_personalized_email_content(lead, location, business_type)
                if lead.row_number is not None:  # Check if row_number is set
                    worksheet.update_cell(lead.row_number, 8, email_content)

                # Print the email content
                st.subheader(f"Generated Email for {lead.name}:")
                st.text(email_content)

                send_emails = st.radio(f"Do you want to send this email to {lead.name}?", ('Yes', 'No'))

                if send_emails == 'Yes':
                    # Part 3: Email Sending
                    if send_email(smtp_server, smtp_port, smtp_username, smtp_password, smtp_username, lead.email,
                                  "Getting to Know You and Your Business", email_content):
                        st.success(f"Email sent successfully to {lead.name}")
                    else:
                        st.error(f"Failed to send email to {lead.name}")

if __name__ == "__main__":
    app()
