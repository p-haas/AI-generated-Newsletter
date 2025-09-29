# News Tracker - Project Roadmap

## 🎯 Current Status
- [x] ✅ Multi-account Gmail integration using Gmail API tokens stored locally or in Secret Manager (`utils/auth.py`).
- [x] ✅ AI-powered email classification with Gemini 2.5 Flash Lite and structured outputs (`utils/email_processing.py`).
- [x] ✅ Enhanced categorisation metadata captured on each news item (primary & secondary categories, confidence scores).
- [x] ✅ News extraction, enrichment, and deduplication flows driven by Gemini 2.5 models (`utils/news_extraction.py`, `utils/news_deduplication.py`).
- [x] ✅ HTML newsletter generation, sanitisation, and delivery through Gmail (`utils/newsletter`).
- [x] ✅ Pipeline telemetry surfaced via structlog and runtime stats returned from [`main.py`](./main.py).
- [ ] ⚠️ Cloud Run deployment with daily scheduling requires per-project configuration (scripts exist but no active service is bundled).
- [ ] ⚠️ Secret Manager-backed credential rotation and storage need project-specific secrets to be provisioned.
- [ ] ⚠️ Automated regression tests and CI remain to be implemented.

---

## 🚀 Phase 1: Quick Wins (1-2 weeks)

### **AI & Content Quality**
- [ ] **Quote Extraction**: Add best quote from each article
- [ ] **Sentiment Analysis**: Add emoji indicators (📈📉⚖️) for each news item
- [ ] **"Top 3" Section**: Highlight most important stories at newsletter top
- [ ] **Article Importance Scoring**: Rate news relevance 1-5 scale
- [x] **Source Attribution**: Better tracking of which sources contribute content

### **Newsletter Enhancements**
- [ ] **Quick Read Summary**: 2-3 sentence newsletter overview
- [ ] **"Why This Matters"**: Add context/implications for key stories
- [x] ✅ **Better Categories**: Enhanced LLM-based categorization with confidence levels
- [ ] **Weekend Format**: Different layout for weekend digests
- [x] ✅ **Newsletter Statistics**: Show daily stats (sources, articles processed)
- [ ] **Category Confidence Filtering**: Use confidence levels to improve content quality
- [ ] **Multi-Topic Story Handling**: Leverage secondary categories for complex stories

### **Organization & Archiving**
- [ ] **Newsletter Archive**: Save past newsletters outside main directory
- [ ] **Date-stamped Folders**: Organize outputs by date (newsletters/2024-01/)
- [x] **Source Tracking**: Log which sources provide best content
- [x] **Processing Metrics**: Track daily pipeline performance

---

## 📊 **Phase 2: Smart Features (2-4 weeks)**

### **Advanced AI Processing**
- [ ] **Trending Topics**: Identify topics appearing across multiple sources
- [ ] **Historical Context**: "This reminds me of..." connections
- [x] **Story Clustering**: Better grouping of related stories
- [ ] **Key Person Extraction**: Track important people mentioned
- [ ] **Geographic Tagging**: Identify news by region/country

### **Content Enhancement**
- [ ] **Article Summaries**: Improve summary quality with better prompts
- [ ] **"What Changed"**: Track updates to ongoing stories
- [ ] **Impact Assessment**: Predict potential implications of news
- [ ] **Follow-up Suggestions**: "Stories to watch" section
- [ ] **Image/Chart Extraction**: Pull relevant visuals from sources

### **Newsletter Intelligence**
- [ ] **Personalization**: Adapt content based on reading patterns
- [ ] **Length Control**: Different newsletter lengths (brief/detailed)
- [ ] **Topic Focus**: Special editions focused on specific topics
- [ ] **Breaking News**: Urgent news handling outside daily schedule
- [ ] **Weekly Wrap-up**: Comprehensive weekly summary format
- [ ] **Executive Summary Placement**: Surface AI summary prominently at the top of each send

---

## 🔧 **Phase 3: Platform Improvements (1-2 months)**

### **Technical Enhancements**
- [ ] **Error Recovery**: Better handling of API failures
- [ ] **Performance Optimization**: Faster processing times
- [ ] **Backup Sources**: Fallback when primary sources fail
- [ ] **Rate Limiting**: Smarter API usage management
- [ ] **Monitoring Dashboard**: Track system health
- [ ] **LLM Cost Monitoring**: Track Gemini usage and alert on spikes

### **User Experience**
- [ ] **Simple Web UI**: View/edit newsletters before sending
- [ ] **Mobile Optimization**: Better mobile newsletter format
- [ ] **Export Options**: PDF, plain text, or markdown exports
- [ ] **Search Archive**: Search past newsletters by topic/date
- [ ] **Newsletter Preview**: Test format before sending
- [ ] **Reader Feedback Loop**: Collect simple reactions to inform tuning

### **Data & Analytics**
- [ ] **Source Analysis**: Which sources provide best content
- [ ] **Topic Trends**: Track topic popularity over time
- [ ] **Reading Analytics**: Track which sections are most valuable
- [ ] **Content Quality Metrics**: Measure newsletter effectiveness
- [ ] **Usage Statistics**: Daily processing and delivery stats
- [ ] **Model Response Logging**: Persist anonymized prompts/responses for QA

---

## 🌟 **Phase 4: Advanced Features (Future)**

### **Content Discovery**
- [ ] **Additional Sources**: RSS feeds, Reddit, Twitter integration
- [ ] **Custom Keywords**: Track specific topics/companies
- [ ] **Industry Focus**: Specialized newsletters by sector
- [ ] **Language Support**: Multi-language news processing
- [ ] **Podcast Transcripts**: Process audio content

### **Intelligence & Automation**
- [ ] **Predictive Analysis**: Forecast story importance
- [x] ✅ **Auto-categorization**: LLM-based category assignment with confidence scoring
- [ ] **Story Lifecycle**: Track stories from emergence to resolution
- [ ] **Market Impact**: Connect news to market movements
- [ ] **Fact Checking**: Basic verification of claims
- [ ] **Category Analytics**: Track categorization accuracy and patterns
- [ ] **Source Quality Weighting**: Use classification confidence for source scoring

### **Sharing & Collaboration**
- [ ] **Public Archive**: Shareable newsletter archive
- [ ] **Multiple Recipients**: Different newsletters for different audiences
- [ ] **Collaboration**: Allow others to contribute sources
- [ ] **API Access**: Programmatic access to processed news
- [ ] **Integration**: Connect with other productivity tools

---

## 🛠 **Technical Debt & Maintenance**

### **Code Quality**
- [ ] **Unit Tests**: Add comprehensive test coverage
- [ ] **Code Documentation**: Improve function documentation
- [ ] **Error Handling**: More robust error management
- [ ] **Configuration**: Better environment variable management
- [ ] **Logging**: Improved logging and debugging

### **Security & Reliability**
- [ ] **Credential Rotation**: Automated token refresh
- [ ] **Backup Strategy**: Data backup and recovery plan
- [ ] **Health Checks**: Better service monitoring
- [ ] **Cost Optimization**: Monitor and reduce cloud costs
- [ ] **Scalability**: Prepare for increased email volume
