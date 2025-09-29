"""Pydantic models representing structured outputs from the LLM."""

from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class NewsClassificationResult(BaseModel):
    """Result of news classification analysis."""

    is_news: bool = Field(description="Whether the email contains news content")
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence level of the classification"
    )
    reason: str = Field(description="Brief explanation for the classification decision")
    
    # Enhanced categorization at classification stage
    primary_category: Optional[Literal["AI", "Economy", "Stocks", "Private Equity", "Politics", "Technology", "Other"]] = Field(
        default=None,
        description="Primary news category if it's news"
    )
    
    secondary_categories: List[Literal["AI", "Economy", "Stocks", "Private Equity", "Politics", "Technology", "Other"]] = Field(
        default=[],
        description="Additional relevant categories for multi-topic content"
    )
    
    # Keep for backward compatibility but deprecate
    topic_category: Optional[str] = Field(
        description="Main topic if it's news (e.g., 'technology', 'politics', 'economy') - DEPRECATED: Use primary_category"
    )


class NewsItem(BaseModel):
    """Individual news item extracted from email."""

    title: str = Field(description="Clear, descriptive title for the news item")
    summary: str = Field(description="Comprehensive summary of the news content")
    main_topic: str = Field(
        description="Primary topic category (e.g., 'AI', 'Economy', 'Politics')"
    )
    source_urls: List[str] = Field(
        description="List of relevant URLs mentioned in the content"
    )
    key_points: List[str] = Field(
        description="3-5 key points or highlights from the news"
    )


class NewsExtractionResult(BaseModel):
    """Result of news item extraction from an email."""

    items: List[NewsItem] = Field(description="List of extracted news items")


class NewsGroup(BaseModel):
    """Group of related news items."""

    type: Literal["duplicate", "similar", "unique"] = Field(
        description="Type of grouping"
    )
    item_ids: List[int] = Field(description="List of news item IDs in this group")
    group_title: str = Field(description="Consolidated title for the group")
    group_summary: str = Field(description="Comprehensive summary combining all items")


class DeduplicationResult(BaseModel):
    """Result of news deduplication analysis."""

    groups: List[NewsGroup] = Field(description="Groups of related news items")


class NewsSubcategory(BaseModel):
    """Subcategory within a news category."""

    subcategory_name: str = Field(description="Name of the subcategory")
    item_ids: List[int] = Field(description="IDs of news items in this subcategory")
    intro_text: str = Field(
        description="Brief introductory text explaining the theme of this subcategory"
    )


class NewsCategory(BaseModel):
    """Main category of news with subcategories."""

    category_name: str = Field(
        description="Main category name (e.g., 'AI', 'Economy', 'Politics')"
    )
    subcategories: List[NewsSubcategory] = Field(
        description="Subcategories within this main category"
    )


class NewsletterStructure(BaseModel):
    """Complete newsletter structure."""

    newsletter_title: str = Field(
        description="Title for the newsletter including date placeholder"
    )
    categories: List[NewsCategory] = Field(
        description="Main categories with their subcategories"
    )
    executive_summary: str = Field(
        description="Brief executive summary of the day's key news themes"
    )
