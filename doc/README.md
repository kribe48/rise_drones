# RISE.Drone_Platform

## Companion Computer

The companion computers are linked as submodule. In order to enable a
submodule, it must be initialized:

> git submodule init

In order to actually download the companion computers, the submodules
must be updated:

> git submodule update

From now on, the root repository points to a hash of the submodules
and the submodule directories are complete git repository of their
respective companion computer.

## Documentation

The **html** version is generated with the following command:

> make -C doc/ html

The **pdf** version is generated with the following command:
> make -C doc/ latexpdf

### Dependencies

* Sphinx
  > https://www.sphinx-doc.org/en/master/usage/installation.html
* sphinxcontrib-mermaid
  > pip3 install sphinxcontrib-mermaid 
* mermaid-cli
  > npm config set prefix ~/.npm \
  > npm install -g @mermaid-js/mermaid-cli \
  > sudo apt-get install libgbm-dev

### Optional dependencies

* sphinxcontrib.seqdiag
  > pip3 install sphinxcontrib-seqdiag
* GitPython
  > pip3 install GitPython
  
### OSX
Install support for pdflatex: \
	- $> brew install basictex # MUCH smaller than full install of mactex \
	- close terminal \
	- open new terminal \
	- $> sudo tlmgr update --self \
	- $> sudo tlmgr install latexmk tex-gyre wrapfig capt-of framed needspace tabulary varwidth titlesec

## Git

### Configuration

Recommended setting for central workflow:

> git config push.default simple

### Workflow

1. Switch to the master branch:

  > git checkout master

2. Pull the latest changes from the master branch:

  > git pull origin master

  - This should actually never be needed: Resets the index and working
    tree. Any changes to tracked files in the working tree are
    discarded.

> git reset --hard origin/master

3. Create a local branch with the name `feature-branch`:

  > git checkout -b feature-branch

4. Do and commit any changes you want:

  > git commit ...

5. Push branch and add upstream (tracking) reference:

  > git push --set-upstream `<user>` feature-branch

6. Create a pull request for 'feature-branch' on GitHub by visiting:
   `https://github.com/<user>/RISE.drone_platform/pull/new/feature-branch`

7. Go back till 1. and start with a new task.
