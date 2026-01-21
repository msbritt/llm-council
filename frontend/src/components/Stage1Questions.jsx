import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage1Questions.css';

export default function Stage1Questions({ stage0Data, userAnswers, researchResults }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!stage0Data || !stage0Data.stage0_raw || stage0Data.stage0_raw.length === 0) {
    return (
      <div className="stage-section stage1-questions">
        <h2 className="stage-title">Stage 1: Clarifying Questions</h2>
        <p className="no-questions-message">
          The models determined that no clarifying questions were needed for this query.
        </p>
      </div>
    );
  }

  const models = stage0Data.stage0_raw;

  return (
    <div className="stage-section stage1-questions">
      <h2 className="stage-title">Stage 1: Clarifying Questions</h2>
      <p className="stage-description">
        Each model reviewed the question and identified what clarifying information would help provide the best answer.
      </p>

      {/* Research Results Section */}
      {researchResults && Object.keys(researchResults).length > 0 && (
        <div className="research-section">
          <h3>Automatic Research Performed</h3>
          <div className="research-results">
            {Object.entries(researchResults).map(([id, result]) => (
              <details key={id} className="research-item">
                <summary>Research finding</summary>
                <div className="research-content markdown-content">
                  <ReactMarkdown>{result}</ReactMarkdown>
                </div>
              </details>
            ))}
          </div>
        </div>
      )}

      {/* User Answers Section */}
      {userAnswers && Object.keys(userAnswers).length > 0 && (
        <div className="user-answers-section">
          <h3>Your Clarifications</h3>
          <div className="user-answers">
            {Object.entries(userAnswers).map(([id, answer]) => (
              <div key={id} className="user-answer-item">
                <div className="markdown-content">
                  <ReactMarkdown>{answer}</ReactMarkdown>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Model Questions Tabs */}
      <div className="tabs">
        {models.map((modelData, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {modelData.model.split('/').pop()}
          </button>
        ))}
      </div>

      <div className="tab-content">
        {models[activeTab] && (
          <>
            <div className="model-questions">
              <h3>Raw Response</h3>
              <div className="markdown-content">
                <ReactMarkdown>{models[activeTab].raw_response}</ReactMarkdown>
              </div>
            </div>

            {models[activeTab].questions && models[activeTab].questions.length > 0 && (
              <div className="parsed-questions">
                <h3>Parsed Questions</h3>
                <ul className="question-list">
                  {models[activeTab].questions.map((q, idx) => (
                    <li key={idx} className={`question-item ${q.type.toLowerCase()}`}>
                      <span className="question-type">[{q.type}]</span>
                      <span className="question-text">{q.question}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
