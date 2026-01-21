import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './ClarificationRound.css';

export default function ClarificationRound({
  userQuestions,
  researchResults,
  stage0Raw,
  onSubmit,
  onSkip,
}) {
  const [answers, setAnswers] = useState({});
  const [activeTab, setActiveTab] = useState(0);

  const handleAnswerChange = (questionId, value) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: value,
    }));
  };

  const handleSubmit = () => {
    onSubmit(answers);
  };

  const allQuestionsAnswered =
    userQuestions.length === 0 ||
    userQuestions.every((q) => answers[q.id] && answers[q.id].trim());

  // Get models that have questions
  const modelsWithQuestions = stage0Raw?.filter(
    (model) => model.questions && model.questions.length > 0
  ) || [];

  return (
    <div className="clarification-round">
      <div className="clarification-header">
        <h3>Stage 1: Clarifying Questions</h3>
        <p>
          The council has reviewed your question. Below you can see what each model asked,
          followed by the consolidated questions for you to answer.
        </p>
      </div>

      {/* Raw Model Questions - Tabbed View */}
      {modelsWithQuestions.length > 0 && (
        <div className="model-questions-section">
          <h4>Questions from Each Model</h4>
          <p className="section-note">
            Each model identified what clarifying information would help. Click the tabs to see each model's questions.
          </p>

          <div className="tabs">
            {modelsWithQuestions.map((modelData, index) => (
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
            {modelsWithQuestions[activeTab] && (
              <>
                <div className="raw-response">
                  <h5>Raw Response</h5>
                  <div className="markdown-content">
                    <ReactMarkdown>{modelsWithQuestions[activeTab].raw_response}</ReactMarkdown>
                  </div>
                </div>

                {modelsWithQuestions[activeTab].questions &&
                  modelsWithQuestions[activeTab].questions.length > 0 && (
                    <div className="parsed-questions-list">
                      <h5>Parsed Questions</h5>
                      <ul className="questions-parsed">
                        {modelsWithQuestions[activeTab].questions.map((q, idx) => (
                          <li key={idx} className={`parsed-question ${q.type.toLowerCase()}`}>
                            <span className="question-type-badge">[{q.type}]</span>
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
      )}

      {/* Research results (auto-fetched) */}
      {researchResults && Object.keys(researchResults).length > 0 && (
        <div className="research-section">
          <h4>Background Research</h4>
          <p className="research-note">
            The council automatically researched some information to help answer
            your question:
          </p>
          <div className="research-results">
            {Object.entries(researchResults).map(([id, result]) => (
              <details key={id} className="research-item">
                <summary>Research finding</summary>
                <div className="research-content">{result}</div>
              </details>
            ))}
          </div>
        </div>
      )}

      {/* User questions - Consolidated for input */}
      {userQuestions && userQuestions.length > 0 && (
        <div className="user-questions-section">
          <h4>Consolidated Questions for You</h4>
          <p className="section-note">
            The chairman has consolidated the most important questions that need your input:
          </p>
          <div className="questions-list">
            {userQuestions.map((q) => (
              <div key={q.id} className="question-item">
                <label htmlFor={q.id}>{q.question}</label>
                <textarea
                  id={q.id}
                  value={answers[q.id] || ''}
                  onChange={(e) => handleAnswerChange(q.id, e.target.value)}
                  placeholder="Your answer..."
                  rows={2}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="clarification-actions">
        <button
          className="submit-button"
          onClick={handleSubmit}
          disabled={!allQuestionsAnswered}
        >
          Submit Answers
        </button>
        <button className="skip-button" onClick={onSkip}>
          Skip Questions
        </button>
      </div>
    </div>
  );
}
