axel
====

Future project to search scientific articles using pre-defined conceps.


Brief details
=============

* We somehow collect research articles from different confrences
* Process all the articles to text, stem, build inverted index
* Load the dictionary of scientific concepts from Computer Science to the system
* Identify all possible concepts inside the article texts, store only TF data
* Create an interface to search for the articles with the concepts you interested in, rank by TF-IDF.
* PROFIT!


Implementation details
======================

* Applcation should consist of 2 pages initially: one for selecting concepts and another for showings the results.
  * Select concepts page: user autocomplete for concept choosing, then show them as labels