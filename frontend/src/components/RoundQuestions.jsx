import React, { useState } from 'react';
import './RoundQuestions.css';

export default function RoundQuestions({ questions, onSubmit, searchCount }) {
  const [answers, setAnswers] = useState({});

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(answers);
  };

  return (
    <div className="round-questions">
      <h3>Questions for you:</h3>

      <form onSubmit={handleSubmit}>
        {questions.map((q, idx) => (
          <div key={idx} className="question-item">
            <label>
              {idx + 1}. {q.text}
              <span className="asked-by">
                ({q.asked_by.map(m => m.split('/').pop()).join(', ')})
              </span>
            </label>
            <input
              type="text"
              value={answers[q.text] || ''}
              onChange={(e) => setAnswers(prev => ({
                ...prev,
                [q.text]: e.target.value
              }))}
              placeholder="Your answer..."
            />
          </div>
        ))}

        {searchCount > 0 && (
          <div className="search-info">
            Searches completed: {searchCount}
          </div>
        )}

        <div className="question-actions">
          <button type="submit" className="submit-btn">
            Submit Answers
          </button>
          <button
            type="button"
            className="skip-btn"
            onClick={() => onSubmit({})}
          >
            Skip Round
          </button>
        </div>
      </form>
    </div>
  );
}
